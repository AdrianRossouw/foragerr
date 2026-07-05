"""FRG-DL-012/006 — pub_date survives the grab hand-off and powers the usenet
SameNzb blocklist match (the same bad post under a NEW guid is caught).

Regression for the P0 bug where ``pub_date`` was dropped at the grab hand-off
(``grab_history.pub_date`` always NULL) AND ``BlocklistEntry.matches`` required
``publish_date`` equality on the usenet branch — so every usenet candidate that
resurfaced under a new guid slipped past the blocklist. Exercised through the
REAL path (the live grab handler + failure loop + BlocklistSpecification), never
by constructing a ``BlocklistEntry`` directly — that is how the bug hid.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from foragerr.commands.service import HandlerContext, daemon_offload
from foragerr.config import Settings
from foragerr.downloads.clients.base import ClientItemStatus
from foragerr.downloads.models import BlocklistRow, GrabHistoryRow
from foragerr.downloads.state import TrackedDownloadState
from foragerr.downloads.stores import load_blocklist_store
from foragerr.downloads.tracking import (
    ClientObservation,
    process_failures,
    reconcile_downloads,
)
from foragerr.library.models import SeriesRow
from foragerr.releases import ReleaseCandidate
from foragerr.search import DecisionEngine, EvaluationContext
from foragerr.search_ops.context import build_evaluation_context
from foragerr.search_ops.grab import GrabReleaseCommand, _handle_grab_release
from tracking_support import FakeCommands, make_item, seed_library

_PUB = dt.datetime(2024, 3, 4, 12, 0, 0)


class _StubClient:
    """A minimal grab-target client that records nothing but a download id."""

    def __init__(self, download_id="nzo-pub") -> None:
        self._download_id = download_id
        # Both spellings so the test is robust to the client_id contract change.
        self._client_id = 5
        self.client_id = 5

    async def download(self, request) -> str:
        return self._download_id


def _patch_resolution(monkeypatch, client, *, protocol="usenet"):
    import foragerr.downloads as downloads_pkg
    import foragerr.downloads.resolver as resolver

    async def _protocol(db, request):
        return protocol

    async def _resolve_grab(db, request, **kwargs):
        return client

    async def _resolve(db, proto, **kwargs):
        return client

    monkeypatch.setattr(resolver, "protocol_for_grab", _protocol)
    monkeypatch.setattr(resolver, "resolve_client_for_grab", _resolve_grab)
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


def _candidate(*, guid, series_title="Spawn"):
    return ReleaseCandidate(
        guid=guid,
        title="Spawn 001 (2024)",
        link="https://idx.test/nzb/resurface",
        indexer_id=7,
        indexer_name="DogNZB",
        indexer_priority=10,
        query_tier=0,
        size_bytes=12345,
        pub_date=_PUB,
        categories=(),
    )


@pytest.mark.req("FRG-DL-006")
@pytest.mark.req("FRG-DL-012")
async def test_pubdate_persists_and_resurfacing_guid_is_blocklisted(db, tmp_path, monkeypatch):
    series_id, issue_id = await seed_library(db, tmp_path)
    _patch_resolution(monkeypatch, _StubClient(download_id="nzo-pub"))

    command = GrabReleaseCommand(
        indexer_id=7,
        guid="G1",
        link="https://idx.test/nzb/1",
        title="Spawn 001 (2024)",
        size_bytes=12345,
        pub_date=_PUB,
        series_id=series_id,
        issue_id=issue_id,
        indexer_name="DogNZB",
    )
    await _handle_grab_release(command, _ctx(db))

    # 1) pub_date survived the hand-off (the dropped-field bug).
    async with db.read_session() as session:
        grab = (
            await session.execute(select(GrabHistoryRow))
        ).scalars().one()
    assert grab.pub_date == _PUB
    client_id = grab.client_id

    # 2) fail it through the real reconcile + failure loop.
    obs = ClientObservation(
        client_id=client_id,
        client_name="SAB",
        protocol="usenet",
        item=make_item("nzo-pub", status=ClientItemStatus.FAILED, reason="unpack failed"),
    )
    await reconcile_downloads(db, [obs], polled_client_ids={client_id})
    await process_failures(db, commands=FakeCommands(), settings=None)

    async with db.read_session() as session:
        block = (await session.execute(select(BlocklistRow))).scalars().one()
    assert block.publish_date == _PUB  # carried onto the blocklist

    # 3) the SAME post resurfacing under a DIFFERENT guid is rejected as
    #    blocklisted, via the real BlocklistSpecification + build_evaluation_context.
    async with db.read_session() as session:
        series = await session.get(SeriesRow, series_id)
        ctx = await build_evaluation_context(session, series, issue_id=issue_id)
    engine = DecisionEngine()
    resurfaced = engine.evaluate(_candidate(guid="G2-different"), ctx)
    assert any(r.spec == "blocklist" for r in resurfaced.rejections)


@pytest.mark.req("FRG-DL-012")
async def test_missing_pubdate_on_candidate_does_not_veto_the_match(db):
    """A candidate with no pub_date must still be caught by a title+indexer+size
    blocklist entry (pub_date is a tie-checker, never a mandatory key)."""
    async with db.write_session() as session:
        session.add(
            BlocklistRow(
                guid="OLD",
                indexer_id=7,
                indexer_name="DogNZB",
                source_title="Spawn 001 (2024)",
                size_bytes=12345,
                publish_date=_PUB,
                protocol="usenet",
                source="indexer",
                created_at=dt.datetime(2024, 1, 1),
            )
        )
    async with db.read_session() as session:
        store = await load_blocklist_store(session)
    # New guid, and this resurfaced result carries NO pub_date.
    candidate = ReleaseCandidate(
        guid="NEW",
        title="Spawn 001 (2024)",
        link="https://idx.test/nzb/x",
        indexer_id=7,
        indexer_name="DogNZB",
        indexer_priority=10,
        query_tier=0,
        size_bytes=12345,
        pub_date=None,
        categories=(),
    )
    assert store.is_blocklisted(candidate) is True
