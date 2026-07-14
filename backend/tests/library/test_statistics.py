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


@pytest.mark.req("FRG-SER-009")
async def test_missing_count_is_the_wanted_count_one_definition(
    db, root_folder_id, format_profile_id
):
    """missing_count uses the wanted predicate (FRG-SER-004), not
    issue_count - file_count: unreleased and unmonitored file-less issues are
    NOT missing, and the count equals the wanted list for the series.
    """
    as_of = dt.date(2026, 1, 1)
    past = dt.date(2025, 6, 1)  # released
    future = dt.date(2026, 6, 1)  # not yet released

    async with db.write_session() as session:
        series = await repo.create_series(
            session,
            cv_volume_id=42,
            title="Wanted Def Series",
            format_profile_id=format_profile_id,
            root_folder_id=root_folder_id,
            path="/tmp/comics/Wanted Def Series",
            monitored=True,
        )
        series_id = series.id
        n = 0

        # 3 released, monitored, file-less  -> MISSING
        for _ in range(3):
            n += 1
            await repo.create_issue(
                session, series_id=series_id, cv_issue_id=1000 + n,
                issue_number=str(n), store_date=past, monitored=True,
            )
        # 2 unreleased (future), monitored, file-less  -> NOT missing
        for _ in range(2):
            n += 1
            await repo.create_issue(
                session, series_id=series_id, cv_issue_id=1000 + n,
                issue_number=str(n), store_date=future, monitored=True,
            )
        # 1 released, UNmonitored, file-less  -> NOT missing
        n += 1
        await repo.create_issue(
            session, series_id=series_id, cv_issue_id=1000 + n,
            issue_number=str(n), store_date=past, monitored=False,
        )
        # 4 released, monitored, WITH a file  -> NOT missing
        for _ in range(4):
            n += 1
            issue = await repo.create_issue(
                session, series_id=series_id, cv_issue_id=1000 + n,
                issue_number=str(n), store_date=past, monitored=True,
            )
            await repo.add_issue_file(
                session, issue_id=issue.id,
                path=f"/tmp/comics/Wanted Def Series/{issue.id}.cbz", size=100,
            )

    async with db.read_session() as session:
        stats = await repo.series_statistics(session, series_id, as_of=as_of)
        # The wanted list restricted to this series (wanted is library-wide).
        series_wanted = await session.execute(
            repo.wanted_issues(as_of).where(
                repo.IssueRow.series_id == series_id
            )
        )
        series_wanted_count = len(series_wanted.scalars().all())

    assert stats.issue_count == 10
    assert stats.file_count == 4
    # The old shortcut would have said 10 - 4 = 6.
    assert stats.issue_count - stats.file_count == 6
    # The correct wanted-aligned count excludes the 2 unreleased + 1 unmonitored.
    assert stats.missing_count == 3
    # Single definition: missing_count equals the wanted list for the series.
    assert stats.missing_count == series_wanted_count
