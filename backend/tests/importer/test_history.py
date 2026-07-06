"""Import history events: in-transaction writes + queries (FRG-PP-011)."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import func, select

from foragerr.importer import history
from foragerr.importer.models import ImportHistoryRow


@pytest.mark.req("FRG-PP-011")
async def test_event_written_in_the_same_transaction(db):
    async with db.write_session() as session:
        history.record_event(
            session,
            event_type=history.EVENT_IMPORTED,
            series_id=1,
            issue_id=7,
            download_id="dl-1",
            source_title="Batman 404 (1987)",
            source=history.SOURCE_DOWNLOAD,
            data={"reasons": [], "provenance": {"series": "grab_record"}},
        )
    async with db.read_session() as session:
        rows = (await session.execute(select(ImportHistoryRow))).scalars().all()
    assert len(rows) == 1
    assert rows[0].event_type == "imported"
    assert history.decode_data(rows[0].data)["provenance"]["series"] == "grab_record"


@pytest.mark.req("FRG-PP-011")
async def test_rollback_discards_the_event(db):
    class Boom(RuntimeError):
        pass

    with pytest.raises(Boom):
        async with db.write_session() as session:
            history.record_event(session, event_type=history.EVENT_IMPORT_BLOCKED)
            raise Boom
    async with db.read_session() as session:
        count = await session.scalar(select(func.count()).select_from(ImportHistoryRow))
    assert count == 0


@pytest.mark.req("FRG-PP-011")
async def test_events_queryable_per_issue_and_globally_ordered(db):
    base = dt.datetime(2026, 7, 5, 10, 0, 0)
    async with db.write_session() as session:
        history.record_event(
            session,
            event_type=history.EVENT_GRABBED,
            issue_id=7,
            download_id="dl-1",
            now=base,
        )
        history.record_event(
            session,
            event_type=history.EVENT_IMPORTED,
            issue_id=7,
            download_id="dl-1",
            now=base + dt.timedelta(minutes=1),
        )
        history.record_event(
            session,
            event_type=history.EVENT_UPGRADE_REPLACED,
            issue_id=7,
            download_id="dl-1",
            quarantine_path="/config/quarantine/2026-07-05/old.cbz",
            now=base + dt.timedelta(hours=2),
        )
        # An unrelated issue's event must not appear in the per-issue query.
        history.record_event(session, event_type=history.EVENT_IMPORTED, issue_id=99)

    async with db.read_session() as session:
        per_issue = await history.events_for_issue(session, 7)
        per_download = await history.events_for_download(session, "dl-1")
        everything = await history.all_events(session)

    assert [r.event_type for r in per_issue] == ["grabbed", "imported", "upgrade_replaced"]
    assert [r.event_type for r in per_download] == ["grabbed", "imported", "upgrade_replaced"]
    assert per_issue[-1].quarantine_path.endswith("old.cbz")
    assert len(everything) == 4  # global feed includes the unrelated issue
