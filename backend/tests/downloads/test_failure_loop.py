"""FRG-DL-011/012/013 — failure loop: fail -> blocklist -> re-search -> reject."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from foragerr.db import CommandRow
from foragerr.downloads.clients.base import ClientItemStatus
from foragerr.downloads.models import SOURCE_DDL, SOURCE_INDEXER
from foragerr.downloads.state import TrackedDownloadState
from foragerr.downloads.stores import load_blocklist_store
from foragerr.downloads.tracking import (
    ClientObservation,
    DownloadFailedEvent,
    process_failures,
    reconcile_downloads,
)
from foragerr.events import EventBus
from foragerr.releases import ReleaseCandidate
from foragerr.search import DecisionEngine, EvaluationContext
from tracking_support import (
    FakeCommands,
    insert_grab_history,
    insert_tracked,
    make_item,
    tracked_by_download_id,
    blocklist_rows,
)

_AUTO = SimpleNamespace(auto_redownload_failed=True)


def _candidate(*, guid="G1", indexer_id=7, indexer_name="DogNZB", size=12345, link="https://idx.test/nzb/1", title="Spawn 001 (2024)"):
    import datetime as dt

    return ReleaseCandidate(
        guid=guid,
        title=title,
        link=link,
        indexer_id=indexer_id,
        indexer_name=indexer_name,
        indexer_priority=10,
        query_tier=0,
        size_bytes=size,
        pub_date=None,
        categories=(),
    )


@pytest.mark.req("FRG-DL-011")
@pytest.mark.req("FRG-DL-012")
@pytest.mark.req("FRG-DL-013")
async def test_failed_download_blocklists_and_enqueues_research(db):
    await insert_grab_history(db, download_id="f1", series_id=1, issue_id=10, guid="G1")
    await insert_tracked(
        db, download_id="f1", state=TrackedDownloadState.FAILED_PENDING,
        series_id=1, issue_id=10,
    )
    commands = FakeCommands()
    await process_failures(db, commands=commands, settings=_AUTO)

    row = await tracked_by_download_id(db, "f1")
    assert row.state == TrackedDownloadState.FAILED.value  # FRG-DL-011

    blocks = await blocklist_rows(db)  # FRG-DL-012
    assert len(blocks) == 1 and blocks[0].guid == "G1" and blocks[0].download_id == "f1"

    assert ("issue-search", {"series_id": 1, "issue_id": 10}, "failure") in commands.enqueued  # FRG-DL-013


@pytest.mark.req("FRG-DL-012")
@pytest.mark.req("FRG-DL-013")
async def test_blocklist_spec_rejects_the_failed_guid_but_not_an_alternative(db):
    await insert_grab_history(db, download_id="f2", series_id=1, issue_id=10, guid="G1")
    await insert_tracked(
        db, download_id="f2", state=TrackedDownloadState.FAILED_PENDING,
        series_id=1, issue_id=10,
    )
    await process_failures(db, commands=FakeCommands(), settings=_AUTO)

    async with db.read_session() as session:
        store = await load_blocklist_store(session)
    engine = DecisionEngine()
    ctx = EvaluationContext(blocklist=store)

    failed = engine.evaluate(_candidate(guid="G1"), ctx)
    alternative = engine.evaluate(_candidate(guid="G2", link="https://idx.test/nzb/2", size=99999), ctx)
    assert any(r.spec == "blocklist" for r in failed.rejections)
    assert not any(r.spec == "blocklist" for r in alternative.rejections)


@pytest.mark.req("FRG-DL-011")
async def test_both_protocols_feed_one_failure_path(db):
    # A usenet failure and a DDL failure drive the IDENTICAL reconcile+process
    # path (the loop imports no ddl code and never branches on client type).
    await insert_grab_history(db, download_id="us", series_id=1, issue_id=10, guid="G1", protocol="usenet", source=SOURCE_INDEXER)
    await insert_grab_history(db, download_id="dd", series_id=2, issue_id=20, guid=None, protocol="ddl", source=SOURCE_DDL, link="https://getcomics.test/post/9")

    usenet = ClientObservation(client_id=1, client_name="SAB", protocol="usenet", item=make_item("us", status=ClientItemStatus.FAILED, reason="unpack failed"))
    ddl = ClientObservation(client_id=2, client_name="DDL", protocol="ddl", item=make_item("dd", status=ClientItemStatus.FAILED, reason="hosts exhausted"))
    await reconcile_downloads(db, [usenet, ddl])
    commands = FakeCommands()
    await process_failures(db, commands=commands, settings=_AUTO)

    assert (await tracked_by_download_id(db, "us")).state == TrackedDownloadState.FAILED.value
    assert (await tracked_by_download_id(db, "dd")).state == TrackedDownloadState.FAILED.value
    blocks = await blocklist_rows(db)
    assert len(blocks) == 2
    ddl_block = next(b for b in blocks if b.download_id == "dd")
    assert ddl_block.source_url == "https://getcomics.test/post/9"  # ddl match key
    enqueued_issues = {(p[1]["series_id"], p[1]["issue_id"]) for p in commands.enqueued}
    assert {(1, 10), (2, 20)} <= enqueued_issues


@pytest.mark.req("FRG-DL-013")
async def test_storm_of_failures_for_one_issue_dedups_within_a_cycle(db):
    # Two distinct failed downloads for the SAME issue -> one re-search.
    for did in ("s1", "s2"):
        await insert_grab_history(db, download_id=did, series_id=1, issue_id=10, guid=did)
        await insert_tracked(db, download_id=did, state=TrackedDownloadState.FAILED_PENDING, series_id=1, issue_id=10)
    commands = FakeCommands()
    await process_failures(db, commands=commands, settings=_AUTO)
    searches = [e for e in commands.enqueued if e[0] == "issue-search"]
    assert len(searches) == 1


@pytest.mark.req("FRG-DL-013")
async def test_command_backbone_dedups_research_across_cycles(db):
    from foragerr.commands.service import CommandService

    commands = CommandService(db)  # not started: enqueue just writes/dedups rows
    for cycle, did in enumerate(("c1", "c2")):
        await insert_grab_history(db, download_id=did, series_id=1, issue_id=10, guid=did)
        await insert_tracked(db, download_id=did, state=TrackedDownloadState.FAILED_PENDING, series_id=1, issue_id=10)
        await process_failures(db, commands=commands, settings=_AUTO)

    async with db.read_session() as session:
        rows = (
            await session.execute(
                select(CommandRow).where(CommandRow.name == "issue-search")
            )
        ).scalars().all()
    assert len(rows) == 1  # equal-bodied re-search collapsed by the backbone


@pytest.mark.req("FRG-DL-013")
async def test_auto_redownload_disabled_enqueues_nothing(db):
    await insert_grab_history(db, download_id="off", series_id=1, issue_id=10, guid="G1")
    await insert_tracked(db, download_id="off", state=TrackedDownloadState.FAILED_PENDING, series_id=1, issue_id=10)
    commands = FakeCommands()
    await process_failures(db, commands=commands, settings=SimpleNamespace(auto_redownload_failed=False))
    assert commands.enqueued == []
    # ...but the blocklist row is still written and the state still advances.
    assert (await tracked_by_download_id(db, "off")).state == TrackedDownloadState.FAILED.value
    assert len(await blocklist_rows(db)) == 1


@pytest.mark.req("FRG-DL-011")
async def test_failure_event_carries_issues_and_grab_data(db):
    bus = EventBus()
    seen: list[DownloadFailedEvent] = []
    bus.subscribe(DownloadFailedEvent, seen.append)
    db.event_publisher = bus.publish

    await insert_grab_history(db, download_id="ev", series_id=1, issue_id=10, guid="G1", indexer_name="DogNZB", size_bytes=555)
    await insert_tracked(db, download_id="ev", state=TrackedDownloadState.FAILED_PENDING, series_id=1, issue_id=10)
    await process_failures(db, commands=FakeCommands(), settings=_AUTO)

    assert len(seen) == 1
    ev = seen[0]
    assert ev.download_id == "ev" and ev.guid == "G1"
    assert ev.issues == ((1, 10),) and ev.indexer_name == "DogNZB" and ev.size_bytes == 555
