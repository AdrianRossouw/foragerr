"""FRG-DL-006 — live grab hand-off: resolve client, download, record history."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from foragerr.commands.service import HandlerContext, daemon_offload
from foragerr.config import Settings
from foragerr.db import utcnow
from foragerr.downloads.errors import (
    DownloadClientUnreachableError,
    GrabValidationError,
    NoDownloadClientError,
)
from foragerr.downloads.models import GrabHistoryRow
from foragerr.search_ops.grab import (
    GrabReleaseCommand,
    _handle_grab_release,
    write_grab_history_rows,
)
from tracking_support import FakeCommands


def _command(**overrides) -> GrabReleaseCommand:
    payload = dict(
        indexer_id=7,
        guid="G1",
        link="https://idx.test/nzb/1",
        title="Spawn 001 (2024)",
        size_bytes=12345,
        series_id=1,
        issue_id=10,
        indexer_name="DogNZB",
    )
    payload.update(overrides)
    return GrabReleaseCommand(**payload)


def _ctx(db, commands=None) -> HandlerContext:
    return HandlerContext(
        db=db,
        bus=None,
        settings=Settings(config_dir="/tmp"),
        offload=daemon_offload,
        commands=commands or FakeCommands(),
    )


async def _grab_history(db) -> list[GrabHistoryRow]:
    async with db.read_session() as session:
        rows = (await session.execute(select(GrabHistoryRow))).scalars().all()
        for r in rows:
            session.expunge(r)
        return list(rows)


class _StubClient:
    _client_id = 3

    def __init__(self, *, download_id="nzo-1", error=None):
        self._download_id = download_id
        self._error = error

    async def download(self, request) -> str:
        if self._error is not None:
            raise self._error
        return self._download_id


def _patch_resolution(monkeypatch, *, client, protocol="usenet"):
    import foragerr.downloads as downloads_pkg
    import foragerr.downloads.resolver as resolver

    async def _protocol(db, request):
        return protocol

    async def _resolve(db, request, **kwargs):
        if isinstance(client, Exception):
            raise client
        return client

    monkeypatch.setattr(resolver, "protocol_for_grab", _protocol)
    monkeypatch.setattr(resolver, "resolve_client_for_grab", _resolve)
    monkeypatch.setattr(downloads_pkg, "make_download_factory", lambda s: None)


@pytest.mark.req("FRG-DL-006")
async def test_multi_issue_release_writes_one_row_per_issue_sharing_id(db):
    async with db.write_session() as session:
        written = await write_grab_history_rows(
            session,
            download_id="SHARED",
            issues=[(1, 10), (1, 11)],
            indexer_id=7,
            indexer_name="DogNZB",
            guid="G1",
            title="Spawn 010-011",
            link="https://idx.test/nzb/1",
            size_bytes=999,
            protocol="usenet",
            source="indexer",
            now=utcnow(),
        )
    assert written == 2
    rows = await _grab_history(db)
    assert {r.issue_id for r in rows} == {10, 11}
    assert {r.download_id for r in rows} == {"SHARED"}  # all share the join key


@pytest.mark.req("FRG-DL-006")
async def test_live_grab_downloads_and_records_history(db, monkeypatch):
    _patch_resolution(monkeypatch, client=_StubClient(download_id="nzo-99"))
    commands = FakeCommands()
    result = await _handle_grab_release(_command(), _ctx(db, commands))

    rows = await _grab_history(db)
    assert len(rows) == 1
    row = rows[0]
    assert row.download_id == "nzo-99"  # the client download id is the join key
    assert row.issue_id == 10 and row.series_id == 1
    assert row.guid == "G1" and row.source == "indexer" and row.client_id == 3
    assert "nzo-99" in result
    # Event-triggers a tracking refresh so the grab surfaces in the queue.
    assert ("track-downloads", {}, "grab") in commands.enqueued


@pytest.mark.req("FRG-DL-006")
async def test_unreachable_client_is_retryable_and_records_nothing(db, monkeypatch):
    _patch_resolution(
        monkeypatch, client=DownloadClientUnreachableError("SAB down")
    )
    with pytest.raises(DownloadClientUnreachableError):
        await _handle_grab_release(_command(), _ctx(db))
    # Never a silent drop: no grab_history row, so the release cache stays the
    # authoritative source and the grab can be retried.
    assert await _grab_history(db) == []


@pytest.mark.req("FRG-DL-006")
async def test_no_enabled_client_is_typed_retryable(db, monkeypatch):
    _patch_resolution(monkeypatch, client=NoDownloadClientError("none enabled"))
    with pytest.raises(NoDownloadClientError):
        await _handle_grab_release(_command(), _ctx(db))
    assert await _grab_history(db) == []


@pytest.mark.req("FRG-DL-006")
async def test_bad_content_fails_the_grab(db, monkeypatch):
    _patch_resolution(
        monkeypatch,
        client=_StubClient(error=GrabValidationError("empty NZB")),
    )
    with pytest.raises(GrabValidationError):
        await _handle_grab_release(_command(), _ctx(db))
    assert await _grab_history(db) == []
