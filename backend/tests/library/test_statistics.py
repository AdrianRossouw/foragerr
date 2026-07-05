"""Per-series statistics: computed via aggregation, never stored (FRG-SER-009)."""

from __future__ import annotations

import datetime as dt

import pytest

from foragerr.library import repo


@pytest.mark.req("FRG-SER-009")
async def test_statistics_aggregate_have_total_and_size_on_disk(
    db, root_folder_id, format_profile_id
):
    async with db.write_session() as session:
        series = await repo.create_series(
            session,
            cv_volume_id=1,
            title="Stats Series",
            format_profile_id=format_profile_id,
            root_folder_id=root_folder_id,
            path="/tmp/comics/Stats Series",
        )
        series_id = series.id
        issue_ids = []
        for n in range(1, 11):  # 10 issues
            issue = await repo.create_issue(
                session, series_id=series_id, cv_issue_id=100 + n, issue_number=str(n)
            )
            issue_ids.append(issue.id)
        for issue_id in issue_ids[:4]:  # 4 have files
            await repo.add_issue_file(
                session, issue_id=issue_id, path=f"/tmp/comics/Stats Series/{issue_id}.cbz", size=1000
            )

    async with db.read_session() as session:
        stats = await repo.series_statistics(session, series_id)

    assert stats.issue_count == 10
    assert stats.file_count == 4
    assert stats.missing_count == 6
    assert stats.size_on_disk == 4000


@pytest.mark.req("FRG-SER-009")
async def test_statistics_update_without_a_manual_recount(
    db, root_folder_id, format_profile_id
):
    async with db.write_session() as session:
        series = await repo.create_series(
            session,
            cv_volume_id=2,
            title="Growing Series",
            format_profile_id=format_profile_id,
            root_folder_id=root_folder_id,
            path="/tmp/comics/Growing Series",
        )
        series_id = series.id
        issue_ids = []
        for n in range(1, 11):
            issue = await repo.create_issue(
                session, series_id=series_id, cv_issue_id=200 + n, issue_number=str(n)
            )
            issue_ids.append(issue.id)
        for issue_id in issue_ids[:4]:
            await repo.add_issue_file(
                session, issue_id=issue_id, path=f"/tmp/comics/Growing Series/{issue_id}.cbz", size=500
            )

    async with db.write_session() as session:
        await repo.add_issue_file(
            session,
            issue_id=issue_ids[4],
            path=f"/tmp/comics/Growing Series/{issue_ids[4]}.cbz",
            size=500,
        )

    async with db.read_session() as session:
        stats = await repo.series_statistics(session, series_id)
    assert stats.file_count == 5
    assert stats.size_on_disk == 2500


@pytest.mark.req("FRG-SER-009")
async def test_statistics_computed_per_request_not_stored(db, root_folder_id, format_profile_id):
    """Complements the schema-inventory test in test_schema.py: fetching
    stats twice with intervening data changes always reflects the live
    aggregate, with no recount action invoked anywhere in this module."""
    async with db.write_session() as session:
        series = await repo.create_series(
            session,
            cv_volume_id=3,
            title="Live Series",
            format_profile_id=format_profile_id,
            root_folder_id=root_folder_id,
            path="/tmp/comics/Live Series",
        )
        series_id = series.id
        issue = await repo.create_issue(
            session, series_id=series_id, cv_issue_id=301, issue_number="1"
        )
        issue_id = issue.id

    async with db.read_session() as session:
        before = await repo.series_statistics(session, series_id)
    assert before.file_count == 0

    async with db.write_session() as session:
        await repo.add_issue_file(
            session, issue_id=issue_id, path="/tmp/comics/Live Series/1.cbz", size=42
        )

    async with db.read_session() as session:
        after = await repo.series_statistics(session, series_id)
    assert after.file_count == 1
    assert after.size_on_disk == 42


@pytest.mark.req("FRG-SER-009")
async def test_next_and_last_release_dates_are_derived(db, root_folder_id, format_profile_id):
    async with db.write_session() as session:
        series = await repo.create_series(
            session,
            cv_volume_id=4,
            title="Dated Series",
            format_profile_id=format_profile_id,
            root_folder_id=root_folder_id,
            path="/tmp/comics/Dated Series",
        )
        series_id = series.id
        today = dt.date.today()
        await repo.create_issue(
            session,
            series_id=series_id,
            cv_issue_id=401,
            issue_number="1",
            store_date=today - dt.timedelta(days=30),
        )
        await repo.create_issue(
            session,
            series_id=series_id,
            cv_issue_id=402,
            issue_number="2",
            store_date=today - dt.timedelta(days=5),
        )
        await repo.create_issue(
            session,
            series_id=series_id,
            cv_issue_id=403,
            issue_number="3",
            store_date=today + dt.timedelta(days=10),
        )

    async with db.read_session() as session:
        stats = await repo.series_statistics(session, series_id, as_of=dt.date.today())
    assert stats.last_release_date == dt.date.today() - dt.timedelta(days=5)
    assert stats.next_release_date == dt.date.today() + dt.timedelta(days=10)
