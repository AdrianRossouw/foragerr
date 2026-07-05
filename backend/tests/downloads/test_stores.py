"""FRG-DL-012/013 — live queue + blocklist stores and their engine wiring."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from foragerr.downloads.state import TrackedDownloadState
from foragerr.downloads.stores import (
    BlocklistEntry,
    BlocklistStore,
    QueueStore,
    load_blocklist_store,
    load_queue_store,
)
from foragerr.library.models import SeriesRow
from foragerr.releases import ReleaseCandidate
from foragerr.search_ops.context import build_evaluation_context
from tracking_support import (
    insert_blocklist,
    insert_tracked,
    seed_library,
)


def _candidate(**overrides) -> ReleaseCandidate:
    payload = dict(
        guid="G1",
        title="Spawn 001 (2024)",
        link="https://idx.test/nzb/1",
        indexer_id=7,
        indexer_name="DogNZB",
        indexer_priority=10,
        query_tier=0,
        size_bytes=12345,
        pub_date=None,
        categories=(),
    )
    payload.update(overrides)
    return ReleaseCandidate(**payload)


@pytest.mark.req("FRG-DL-013")
def test_queue_store_membership():
    store = QueueStore(frozenset({(1, 10)}))
    assert store.is_queued(1, 10) is True
    assert store.is_queued(1, 11) is False


@pytest.mark.req("FRG-DL-012")
def test_blocklist_usenet_multifield_match():
    when = dt.datetime(2024, 1, 1)
    entry = BlocklistEntry(
        guid=None, indexer_id=7, indexer_name="DogNZB", title="Spawn 001 (2024)",
        size_bytes=12345, publish_date=when, protocol="usenet", source="indexer",
        source_url=None,
    )
    store = BlocklistStore((entry,))
    # Same title+indexer+size+publish_date matches even under a NEW guid.
    assert store.is_blocklisted(_candidate(guid="NEW", pub_date=when)) is True
    # A different size is a different post.
    assert store.is_blocklisted(_candidate(guid="NEW", size_bytes=1, pub_date=when)) is False


@pytest.mark.req("FRG-DL-012")
def test_blocklist_ddl_and_guid_matches():
    ddl = BlocklistEntry(
        guid=None, indexer_id=None, indexer_name=None, title=None, size_bytes=None,
        publish_date=None, protocol="ddl", source="ddl",
        source_url="https://getcomics.test/post/9",
    )
    assert BlocklistStore((ddl,)).is_blocklisted(
        _candidate(link="https://getcomics.test/post/9")
    ) is True

    guid_entry = BlocklistEntry(
        guid="G1", indexer_id=7, indexer_name=None, title=None, size_bytes=None,
        publish_date=None, protocol="usenet", source="indexer", source_url=None,
    )
    assert BlocklistStore((guid_entry,)).is_blocklisted(_candidate(guid="G1")) is True


@pytest.mark.req("FRG-DL-013")
async def test_load_queue_store_excludes_failed_and_ignored(db):
    await insert_tracked(db, download_id="active", state=TrackedDownloadState.DOWNLOADING, series_id=1, issue_id=10)
    await insert_tracked(db, download_id="failed", state=TrackedDownloadState.FAILED, series_id=2, issue_id=20)
    await insert_tracked(db, download_id="ignored", state=TrackedDownloadState.IGNORED, series_id=3, issue_id=30)
    async with db.read_session() as session:
        store = await load_queue_store(session)
    assert store.is_queued(1, 10) is True
    assert store.is_queued(2, 20) is False  # failed -> grabbable again
    assert store.is_queued(3, 30) is False


@pytest.mark.req("FRG-DL-012")
@pytest.mark.req("FRG-DL-013")
async def test_build_evaluation_context_injects_live_stores(db, tmp_path):
    series_id, issue_id = await seed_library(db, tmp_path)
    await insert_tracked(
        db, download_id="q", state=TrackedDownloadState.DOWNLOADING,
        series_id=series_id, issue_id=issue_id,
    )
    await insert_blocklist(db, guid="G1", indexer_id=7)

    async with db.read_session() as session:
        series = await session.get(SeriesRow, series_id)
        ctx = await build_evaluation_context(session, series, issue_id=issue_id)

    # The search pipeline now sees a LIVE queue + blocklist, not the inert stubs.
    assert ctx.queue.is_queued(series_id, issue_id) is True
    assert ctx.blocklist.is_blocklisted(_candidate(guid="G1")) is True


@pytest.mark.req("FRG-DL-012")
async def test_deleting_a_blocklist_row_re_enables_grabbing(db):
    from foragerr.downloads.models import BlocklistRow

    await insert_blocklist(db, guid="G1", indexer_id=7)
    async with db.read_session() as session:
        store = await load_blocklist_store(session)
    assert store.is_blocklisted(_candidate(guid="G1")) is True

    async with db.write_session() as session:
        rows = (await session.execute(select(BlocklistRow))).scalars().all()
        for r in rows:
            await session.delete(r)
    async with db.read_session() as session:
        store = await load_blocklist_store(session)
    assert store.is_blocklisted(_candidate(guid="G1")) is False  # grabbable again
