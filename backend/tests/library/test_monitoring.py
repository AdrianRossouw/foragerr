"""Two-level monitoring and derived wanted state (FRG-SER-003, FRG-SER-004)."""

from __future__ import annotations

import datetime as dt

import pytest

from foragerr.library import repo


async def _make_series(db, root_folder_id, format_profile_id, *, cv_volume_id, monitored=True):
    async with db.write_session() as session:
        return (
            await repo.create_series(
                session,
                cv_volume_id=cv_volume_id,
                title=f"Series {cv_volume_id}",
                format_profile_id=format_profile_id,
                root_folder_id=root_folder_id,
                path=f"/tmp/comics/Series {cv_volume_id}",
                monitored=monitored,
            )
        ).id


async def _make_issue(
    db,
    series_id,
    *,
    cv_issue_id,
    issue_number="1",
    monitored=True,
    cover_date=None,
    store_date=None,
):
    async with db.write_session() as session:
        return (
            await repo.create_issue(
                session,
                series_id=series_id,
                cv_issue_id=cv_issue_id,
                issue_number=issue_number,
                monitored=monitored,
                cover_date=cover_date,
                store_date=store_date,
            )
        ).id


@pytest.mark.req("FRG-SER-003")
async def test_unmonitored_series_suppresses_eligibility_of_monitored_issues(
    db, root_folder_id, format_profile_id
):
    series_id = await _make_series(
        db, root_folder_id, format_profile_id, cv_volume_id=1, monitored=False
    )
    issue_id = await _make_issue(db, series_id, cv_issue_id=1, monitored=True)

    async with db.read_session() as session:
        wanted = await repo.wanted_issue_ids(session)
    assert issue_id not in wanted


@pytest.mark.req("FRG-SER-003")
async def test_remonitoring_series_restores_eligibility_without_touching_issue_flags(
    db, root_folder_id, format_profile_id
):
    series_id = await _make_series(
        db, root_folder_id, format_profile_id, cv_volume_id=2, monitored=False
    )
    issue_id = await _make_issue(db, series_id, cv_issue_id=2, monitored=True)

    async with db.read_session() as session:
        assert issue_id not in await repo.wanted_issue_ids(session)

    async with db.write_session() as session:
        await repo.set_series_monitored(session, series_id, True)

    async with db.read_session() as session:
        wanted = await repo.wanted_issue_ids(session)
        from foragerr.library.models import IssueRow

        issue = await session.get(IssueRow, issue_id)
    assert issue_id in wanted
    assert issue.monitored is True  # never written by either toggle


@pytest.mark.req("FRG-SER-003")
async def test_eligibility_requires_both_series_and_issue_monitored(
    db, root_folder_id, format_profile_id
):
    series_id = await _make_series(
        db, root_folder_id, format_profile_id, cv_volume_id=3, monitored=True
    )
    issue_id = await _make_issue(db, series_id, cv_issue_id=3, monitored=False)

    async with db.read_session() as session:
        wanted = await repo.wanted_issue_ids(session)
    assert issue_id not in wanted


@pytest.mark.req("FRG-SER-004")
async def test_no_wanted_column_in_the_schema(db):
    """Schema-inventory scenario duplicate (also asserted in test_schema.py)
    kept alongside the behavioral wanted tests for locality."""
    async with db.engine.connect() as conn:

        def _cols(sync_conn):
            from sqlalchemy import inspect

            return {c["name"].lower() for c in inspect(sync_conn).get_columns("issues")}

        names = await conn.run_sync(_cols)
    assert "wanted" not in names


@pytest.mark.req("FRG-SER-004")
async def test_importing_a_file_removes_the_issue_from_wanted(
    db, root_folder_id, format_profile_id
):
    series_id = await _make_series(db, root_folder_id, format_profile_id, cv_volume_id=4)
    issue_id = await _make_issue(db, series_id, cv_issue_id=4)

    async with db.read_session() as session:
        assert issue_id in await repo.wanted_issue_ids(session)

    async with db.write_session() as session:
        await repo.add_issue_file(
            session, issue_id=issue_id, path="/tmp/comics/Series 4/1.cbz", size=1234
        )

    async with db.read_session() as session:
        wanted = await repo.wanted_issue_ids(session)
        from foragerr.library.models import IssueRow

        issue = await session.get(IssueRow, issue_id)
    assert issue_id not in wanted
    assert issue.monitored is True  # no status column was written


@pytest.mark.req("FRG-SER-004")
async def test_deleting_the_file_returns_the_issue_to_wanted(
    db, root_folder_id, format_profile_id
):
    series_id = await _make_series(db, root_folder_id, format_profile_id, cv_volume_id=5)
    issue_id = await _make_issue(db, series_id, cv_issue_id=5)

    async with db.write_session() as session:
        file_row = await repo.add_issue_file(
            session, issue_id=issue_id, path="/tmp/comics/Series 5/1.cbz", size=1234
        )
        file_id = file_row.id

    async with db.read_session() as session:
        assert issue_id not in await repo.wanted_issue_ids(session)

    async with db.write_session() as session:
        await repo.remove_issue_file(session, file_id)

    async with db.read_session() as session:
        assert issue_id in await repo.wanted_issue_ids(session)


@pytest.mark.req("FRG-SER-004")
async def test_unreleased_monitored_issues_are_not_wanted(
    db, root_folder_id, format_profile_id
):
    series_id = await _make_series(db, root_folder_id, format_profile_id, cv_volume_id=6)
    future = dt.date.today() + dt.timedelta(days=30)
    issue_id = await _make_issue(db, series_id, cv_issue_id=6, store_date=future)

    async with db.read_session() as session:
        wanted = await repo.wanted_issue_ids(session)
    assert issue_id not in wanted


@pytest.mark.req("FRG-SER-004")
async def test_past_release_date_issue_is_wanted(db, root_folder_id, format_profile_id):
    series_id = await _make_series(db, root_folder_id, format_profile_id, cv_volume_id=7)
    past = dt.date.today() - dt.timedelta(days=1)
    issue_id = await _make_issue(db, series_id, cv_issue_id=7, store_date=past)

    async with db.read_session() as session:
        wanted = await repo.wanted_issue_ids(session)
    assert issue_id in wanted


@pytest.mark.req("FRG-SER-004")
async def test_unknown_release_date_is_treated_as_released(
    db, root_folder_id, format_profile_id
):
    series_id = await _make_series(db, root_folder_id, format_profile_id, cv_volume_id=8)
    issue_id = await _make_issue(db, series_id, cv_issue_id=8)  # no dates at all

    async with db.read_session() as session:
        wanted = await repo.wanted_issue_ids(session)
    assert issue_id in wanted
