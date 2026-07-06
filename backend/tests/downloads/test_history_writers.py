"""FRG-API-011 — the two backfilled history writers (m2-daily-surfaces
design decision 1): ``grabbed`` beside the grab_history insert and
``download_failed`` beside the blocklist write, making ``import_history``
the single source the /history feed reads."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from foragerr.commands.service import HandlerContext, daemon_offload
from foragerr.config import Settings
from foragerr.db import utcnow
from foragerr.downloads.models import BlocklistRow, GrabHistoryRow, TrackedDownloadRow
from foragerr.downloads.state import TrackedDownloadState
from foragerr.downloads.tracking import _encode_messages, process_failures
from foragerr.importer import history
from foragerr.importer.context import ImportContext
from foragerr.importer.pipeline import ImportStatus, gather, import_candidate
from foragerr.importer.sources import CompletedDownloadSource
from foragerr.search_ops.grab import GrabReleaseCommand, _handle_grab_release
from importer._archives import make_cbz
from tracking_support import (
    FakeCommands,
    insert_grab_history,
    insert_tracked,
    seed_library,
)


class _StubClient:
    def __init__(self, download_id: str = "nzo-1", client_id: int = 3) -> None:
        self._download_id = download_id
        self._client_id = client_id

    @property
    def client_id(self) -> int:
        return self._client_id

    async def download(self, request) -> str:
        return self._download_id


def _patch_resolution(monkeypatch, *, client, protocol: str = "usenet") -> None:
    import foragerr.downloads as downloads_pkg
    import foragerr.downloads.resolver as resolver

    async def _protocol(db, request):
        return protocol

    async def _resolve(db, proto, **kwargs):
        return client

    monkeypatch.setattr(resolver, "protocol_for_grab", _protocol)
    monkeypatch.setattr(resolver, "resolve_client_for", _resolve)
    monkeypatch.setattr(downloads_pkg, "make_download_factory", lambda s: None)


def _ctx(db) -> HandlerContext:
    return HandlerContext(
        db=db,
        bus=None,
        settings=Settings(config_dir="/tmp"),
        offload=daemon_offload,
        commands=FakeCommands(),
    )


async def _events_for_download(db, download_id: str):
    async with db.read_session() as session:
        rows = await history.events_for_download(session, download_id)
        for r in rows:
            session.expunge(r)
        return rows


@pytest.mark.req("FRG-API-011")
async def test_grab_writes_a_grabbed_event_beside_the_grab_history_row(
    db, tmp_path, monkeypatch
):
    series_id, issue_id = await seed_library(db, tmp_path)
    _patch_resolution(monkeypatch, client=_StubClient(download_id="nzo-77"))
    command = GrabReleaseCommand(
        indexer_id=7,
        guid="G1",
        link="https://idx.test/nzb/1",
        title="Spawn 001 (2024)",
        size_bytes=12345,
        series_id=series_id,
        issue_id=issue_id,
        indexer_name="DogNZB",
    )
    await _handle_grab_release(command, _ctx(db))

    # Both records exist, joined by the client download id, written in the
    # same transaction (a single write_session commit).
    async with db.read_session() as session:
        grabs = (await session.execute(select(GrabHistoryRow))).scalars().all()
        assert len(grabs) == 1 and grabs[0].download_id == "nzo-77"
    events = await _events_for_download(db, "nzo-77")
    assert [e.event_type for e in events] == [history.EVENT_GRABBED]
    grabbed = events[0]
    assert grabbed.series_id == series_id and grabbed.issue_id == issue_id
    assert grabbed.source_title == "Spawn 001 (2024)"
    data = history.decode_data(grabbed.data)
    assert data["indexer"] == "DogNZB" and data["protocol"] == "usenet"


@pytest.mark.req("FRG-API-011")
async def test_grab_then_import_cycle_shares_the_download_id(
    db, tmp_path, monkeypatch
):
    series_id, issue_id = await seed_library(db, tmp_path)
    _patch_resolution(monkeypatch, client=_StubClient(download_id="nzo-1"))
    command = GrabReleaseCommand(
        indexer_id=7,
        guid="G1",
        link="https://idx.test/nzb/1",
        title="Spawn 001 (2024)",
        size_bytes=12345,
        series_id=series_id,
        issue_id=issue_id,
        indexer_name="DogNZB",
    )
    await _handle_grab_release(command, _ctx(db))

    # The download completes; the pipeline imports it (the real import path).
    dl_dir = tmp_path / "dl" / "Spawn.001"
    make_cbz(dl_dir / "Spawn 001 (2024).cbz")
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    ctx = ImportContext(
        library_root=str(tmp_path / "lib-root"),
        config_dir=str(config_dir),
        reference_year=2026,
        free_space_margin_bytes=0,
        junk_size_floor_bytes=64,
        now=utcnow(),  # after the grab's own utcnow() stamp
    )
    source = CompletedDownloadSource(download_id="nzo-1", output_path=str(dl_dir))
    async with db.write_session() as session:
        outcomes = [
            await import_candidate(session, cand, ctx)
            for cand in await gather(source, session, ctx)
        ]
    assert [o.status for o in outcomes] == [ImportStatus.IMPORTED]

    # One grabbed + one imported event, joined by the shared downloadId
    # (FRG-API-011 scenario 1) — no grab_history/blocklist union needed.
    events = await _events_for_download(db, "nzo-1")
    assert [e.event_type for e in events] == [
        history.EVENT_GRABBED,
        history.EVENT_IMPORTED,
    ]
    assert {e.download_id for e in events} == {"nzo-1"}
    assert {e.series_id for e in events} == {series_id}
    assert {e.issue_id for e in events} == {issue_id}


@pytest.mark.req("FRG-API-011")
async def test_download_failure_writes_a_download_failed_event(db, tmp_path):
    series_id, issue_id = await seed_library(db, tmp_path)
    await insert_grab_history(
        db, download_id="f1", series_id=series_id, issue_id=issue_id, guid="G1"
    )
    row_id = await insert_tracked(
        db,
        download_id="f1",
        state=TrackedDownloadState.FAILED_PENDING,
        series_id=series_id,
        issue_id=issue_id,
    )
    async with db.write_session() as session:
        row = await session.get(TrackedDownloadRow, row_id)
        row.status_messages = _encode_messages(["unpack failed"])
    await process_failures(db, commands=FakeCommands())

    # The blocklist row (the operational record) AND the history event (the
    # user-facing feed) land together, in the same transaction.
    async with db.read_session() as session:
        blocks = (await session.execute(select(BlocklistRow))).scalars().all()
        assert len(blocks) == 1
    events = await _events_for_download(db, "f1")
    assert [e.event_type for e in events] == [history.EVENT_DOWNLOAD_FAILED]
    failed = events[0]
    assert failed.download_id == "f1"
    data = history.decode_data(failed.data)
    assert data["downloadId"] == "f1"
    assert data["message"] == "unpack failed"
