"""Schema round-trips and the schema-inventory guard (FRG-SER-001, 002, 004,
009, FRG-DB-008)."""

from __future__ import annotations

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import StatementError

from foragerr.library import repo
from foragerr.library.models import IssueFileRow, IssueRow, SeriesRow


@pytest.mark.req("FRG-SER-001")
async def test_stored_series_round_trips_all_baseline_fields(
    db, root_folder_id, format_profile_id
):
    async with db.write_session() as session:
        row = await repo.create_series(
            session,
            cv_volume_id=4050,
            title="Saga",
            sort_title="Saga",
            publisher="Image",
            start_year=2012,
            status="continuing",
            format_profile_id=format_profile_id,
            root_folder_id=root_folder_id,
            path="/tmp/comics/Saga (2012)",
            description_sanitized="A space opera.",
        )
        series_id = row.id

    async with db.read_session() as session:
        fetched = await session.get(SeriesRow, series_id)
    assert fetched.title == "Saga"
    assert fetched.sort_title == "Saga"
    assert fetched.publisher == "Image"
    assert fetched.start_year == 2012
    assert fetched.status == "continuing"
    assert fetched.cover_cached_at is None
    assert fetched.path == "/tmp/comics/Saga (2012)"
    assert fetched.root_folder_id == root_folder_id
    assert fetched.format_profile_id == format_profile_id
    assert fetched.monitored is True
    assert fetched.added_at is not None
    assert fetched.refreshed_at is None
    assert fetched.description_sanitized == "A space opera."


@pytest.mark.req("FRG-SER-001")
async def test_duplicate_cv_volume_id_is_rejected(db, root_folder_id, format_profile_id):
    async with db.write_session() as session:
        await repo.create_series(
            session,
            cv_volume_id=4050,
            title="Saga",
            format_profile_id=format_profile_id,
            root_folder_id=root_folder_id,
            path="/tmp/comics/Saga",
        )

    with pytest.raises(Exception):  # IntegrityError from the unique constraint
        async with db.write_session() as session:
            await repo.create_series(
                session,
                cv_volume_id=4050,
                title="Saga Duplicate",
                format_profile_id=format_profile_id,
                root_folder_id=root_folder_id,
                path="/tmp/comics/Saga Duplicate",
            )

    async with db.read_session() as session:
        rows = (
            (await session.execute(select(SeriesRow).where(SeriesRow.cv_volume_id == 4050)))
            .scalars()
            .all()
        )
    assert len(rows) == 1


@pytest.mark.req("FRG-SER-001")
async def test_series_persists_and_round_trips_the_default_format_profile_reference(
    db, root_folder_id, format_profile_id
):
    """Repo-level slice of FRG-SER-001's "new series receives the default
    format profile" scenario: the row correctly stores/round-trips whatever
    `format_profile_id` it is given, here the seeded default's id. Choosing
    the default automatically when the caller omits a profile is an
    add-flow (change 3) policy decision layered on top of this repo
    function, not this repo's job (see `foragerr.quality.models` docstring
    for how the default profile is identified)."""
    async with db.write_session() as session:
        row = await repo.create_series(
            session,
            cv_volume_id=999,
            title="East of West",
            format_profile_id=format_profile_id,
            root_folder_id=root_folder_id,
            path="/tmp/comics/East of West",
        )
    assert row.format_profile_id == format_profile_id


@pytest.mark.req("FRG-SER-002")
async def test_non_integer_issue_numbers_persist_verbatim_as_text(
    db, root_folder_id, format_profile_id
):
    async with db.write_session() as session:
        series = await repo.create_series(
            session,
            cv_volume_id=1,
            title="Test Series",
            format_profile_id=format_profile_id,
            root_folder_id=root_folder_id,
            path="/tmp/comics/Test Series",
        )
        series_id = series.id
        for cv_id, number in [(10, "1"), (11, "1.5"), (12, "1.MU")]:
            await repo.create_issue(
                session, series_id=series_id, cv_issue_id=cv_id, issue_number=number
            )

    async with db.read_session() as session:
        issues = await repo.list_issues_for_series(session, series_id)
    assert {i.issue_number for i in issues} == {"1", "1.5", "1.MU"}

    with pytest.raises(TypeError):
        async with db.write_session() as session:
            await repo.create_issue(
                session, series_id=series_id, cv_issue_id=99, issue_number=1.5  # not a str
            )


@pytest.mark.req("FRG-SER-002")
async def test_issues_list_in_reading_order_via_the_persisted_key(
    db, root_folder_id, format_profile_id
):
    async with db.write_session() as session:
        series = await repo.create_series(
            session,
            cv_volume_id=2,
            title="Reading Order",
            format_profile_id=format_profile_id,
            root_folder_id=root_folder_id,
            path="/tmp/comics/Reading Order",
        )
        series_id = series.id
        # Inserted out of reading order deliberately.
        for cv_id, number in [(21, "10"), (22, "1"), (23, "2")]:
            await repo.create_issue(
                session, series_id=series_id, cv_issue_id=cv_id, issue_number=number
            )

    async with db.read_session() as session:
        issues = await repo.list_issues_for_series(session, series_id)
    assert [i.issue_number for i in issues] == ["1", "2", "10"]


@pytest.mark.req("FRG-SER-002")
async def test_absent_dates_and_files_are_null_not_sentinels(
    db, root_folder_id, format_profile_id
):
    async with db.write_session() as session:
        series = await repo.create_series(
            session,
            cv_volume_id=3,
            title="No Dates",
            format_profile_id=format_profile_id,
            root_folder_id=root_folder_id,
            path="/tmp/comics/No Dates",
        )
        issue = await repo.create_issue(
            session, series_id=series.id, cv_issue_id=31, issue_number="1"
        )
        issue_id = issue.id

    async with db.read_session() as session:
        fetched = await session.get(IssueRow, issue_id)
        assert fetched.store_date is None
        assert fetched.cover_date is None
        files = (
            (await session.execute(select(IssueFileRow).where(IssueFileRow.issue_id == issue_id)))
            .scalars()
            .all()
        )
        assert files == []  # no issue-file row: null, not a placeholder


@pytest.mark.req("FRG-SER-002")
async def test_issue_monitored_toggle_does_not_affect_siblings(
    db, root_folder_id, format_profile_id
):
    async with db.write_session() as session:
        series = await repo.create_series(
            session,
            cv_volume_id=4,
            title="Siblings",
            format_profile_id=format_profile_id,
            root_folder_id=root_folder_id,
            path="/tmp/comics/Siblings",
        )
        one = await repo.create_issue(
            session, series_id=series.id, cv_issue_id=41, issue_number="1"
        )
        two = await repo.create_issue(
            session, series_id=series.id, cv_issue_id=42, issue_number="2"
        )
        one_id, two_id = one.id, two.id

    async with db.write_session() as session:
        await repo.set_issue_monitored(session, one_id, False)

    async with db.read_session() as session:
        fetched_one = await session.get(IssueRow, one_id)
        fetched_two = await session.get(IssueRow, two_id)
    assert fetched_one.monitored is False
    assert fetched_two.monitored is True


@pytest.mark.req("FRG-DB-008")
async def test_series_free_text_sentinel_strings_normalize_to_null(
    db, root_folder_id, format_profile_id
):
    """Sentinel-prone external free-text fields (publisher, description) use
    `SentinelFreeText`: a sentinel-shaped string from an external source
    normalizes to SQL NULL, exactly like the generic column-convention
    suite in test_db_models.py — exercised here against the real series
    table rather than a throwaway convention model."""
    async with db.write_session() as session:
        row = await repo.create_series(
            session,
            cv_volume_id=5000,
            title="Sentinel Publisher Series",
            publisher="None",  # sentinel-shaped external string
            format_profile_id=format_profile_id,
            root_folder_id=root_folder_id,
            path="/tmp/comics/Sentinel Publisher Series",
            description_sanitized="null",
        )
        series_id = row.id

    async with db.read_session() as session:
        fetched = await session.get(SeriesRow, series_id)
    assert fetched.publisher is None
    assert fetched.description_sanitized is None


@pytest.mark.req("FRG-DB-008")
async def test_series_and_issue_typed_columns_reject_mistyped_values(
    db, root_folder_id, format_profile_id
):
    with pytest.raises(StatementError):
        async with db.write_session() as session:
            await repo.create_series(
                session,
                cv_volume_id=5001,
                title="Bad Year",
                start_year="two thousand twelve",  # not an int
                format_profile_id=format_profile_id,
                root_folder_id=root_folder_id,
                path="/tmp/comics/Bad Year",
            )

    async with db.write_session() as session:
        series = await repo.create_series(
            session,
            cv_volume_id=5002,
            title="Bad Date Holder",
            format_profile_id=format_profile_id,
            root_folder_id=root_folder_id,
            path="/tmp/comics/Bad Date Holder",
        )
        series_id = series.id

    with pytest.raises(StatementError):
        async with db.write_session() as session:
            await repo.create_issue(
                session,
                series_id=series_id,
                cv_issue_id=5003,
                issue_number="1",
                cover_date="0000-00-00",  # classic sentinel date, rejected outright
            )

    async with db.read_session() as session:
        rows = (
            (await session.execute(select(SeriesRow).where(SeriesRow.cv_volume_id.in_([5001]))))
            .scalars()
            .all()
        )
        issue_rows = (
            (await session.execute(select(IssueRow).where(IssueRow.cv_issue_id == 5003)))
            .scalars()
            .all()
        )
    assert rows == []  # the mistyped series never persisted
    assert issue_rows == []  # the mistyped issue never persisted


@pytest.mark.req("FRG-SER-004")
@pytest.mark.req("FRG-SER-009")
async def test_no_wanted_or_stored_statistics_columns_exist_anywhere(db):
    """Schema-inventory guard: `wanted` never exists as a stored column, and
    neither do stored issue/file/missing-count or size-on-disk columns."""
    tables = ("series", "issues", "issue_files")

    def _column_names(sync_conn) -> dict[str, set[str]]:
        inspector = inspect(sync_conn)
        return {
            table: {col["name"].lower() for col in inspector.get_columns(table)}
            for table in tables
        }

    async with db.engine.connect() as conn:
        by_table = await conn.run_sync(_column_names)

    forbidden_wanted = {"wanted", "is_wanted", "wanted_status"}
    forbidden_stats = {
        "issue_count",
        "file_count",
        "missing_count",
        "size_on_disk",
        "size_bytes",
    }
    for table, names in by_table.items():
        assert not (names & forbidden_wanted), f"{table} exposes a stored wanted column"
        assert not (names & forbidden_stats), f"{table} exposes a stored statistics column"
