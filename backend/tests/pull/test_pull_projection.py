"""foragerr.pull.projection — the weekly view (FRG-PULL-001) merged with
stored pull entries (FRG-API-019 area E)."""

from __future__ import annotations

import datetime as dt

import pytest

from foragerr.downloads.models import TrackedDownloadRow
from foragerr.downloads.state import TrackedDownloadState
from foragerr.library import repo as library_repo
from foragerr.pull import repo as pull_repo
from foragerr.pull.models import ParsedPullEntry
from foragerr.pull.projection import (
    MalformedWeek,
    current_week,
    week_date_range,
    weekly_pull,
)

# A fixed week with a known Monday, so tests never depend on "today".
WEEK = "2026-W28"
MONDAY = dt.date(2026, 7, 6)
IN_WEEK = MONDAY + dt.timedelta(days=2)
PREV_WEEK = "2026-W27"
NEXT_WEEK = "2026-W29"


async def _format_profile_id(db) -> int:
    from sqlalchemy import select

    from foragerr.quality.models import DEFAULT_PROFILE_NAME, FormatProfileRow

    async with db.read_session() as session:
        return (
            await session.execute(
                select(FormatProfileRow.id).where(
                    FormatProfileRow.name == DEFAULT_PROFILE_NAME
                )
            )
        ).scalar_one()


async def _seed_series(
    db, tmp_path, *, title: str, cv_volume_id: int, monitored: bool = True
) -> int:
    profile_id = await _format_profile_id(db)
    root = tmp_path / "lib-root"
    root.mkdir(exist_ok=True)
    async with db.write_session() as session:
        rf = await library_repo.create_root_folder(session, str(root / title))
        series = await library_repo.create_series(
            session,
            cv_volume_id=cv_volume_id,
            title=title,
            start_year=2024,
            format_profile_id=profile_id,
            root_folder_id=rf.id,
            path=str(root / title),
            monitored=monitored,
            publisher="Image",
        )
        await session.flush()
        return series.id


async def _seed_issue(
    db,
    *,
    series_id: int,
    cv_issue_id: int,
    number: str,
    store_date: dt.date | None,
    monitored: bool = True,
) -> int:
    async with db.write_session() as session:
        issue = await library_repo.create_issue(
            session,
            series_id=series_id,
            cv_issue_id=cv_issue_id,
            issue_number=number,
            store_date=store_date,
            monitored=monitored,
        )
        await session.flush()
        return issue.id


async def _add_file(db, issue_id: int, path: str) -> None:
    async with db.write_session() as session:
        await library_repo.add_issue_file(session, issue_id=issue_id, path=path, size=1)


async def _track(db, *, issue_id: int, state: TrackedDownloadState, download_id: str) -> None:
    from foragerr.db import utcnow

    async with db.write_session() as session:
        now = utcnow()
        session.add(
            TrackedDownloadRow(
                download_id=download_id,
                client_id=1,
                client_name="SAB",
                protocol="usenet",
                state=state.value,
                status="ok",
                series_id=None,
                issue_id=issue_id,
                added_at=now,
                updated_at=now,
            )
        )


# --- week parsing -------------------------------------------------------------


@pytest.mark.req("FRG-API-019")
def test_current_week_and_range_roundtrip():
    key = current_week(dt.date(2026, 7, 8))  # a Wednesday in ISO week 28, 2026
    assert key == "2026-W28"
    start, end = week_date_range(key)
    assert start == dt.date(2026, 7, 6) and end == dt.date(2026, 7, 12)


@pytest.mark.req("FRG-API-019")
@pytest.mark.parametrize("bad", ["2026", "2026-W1", "not-a-week", "2026-W99", "", "2026-W00"])
def test_malformed_week_rejected(bad):
    with pytest.raises(MalformedWeek):
        week_date_range(bad)


# --- FRG-PULL-001: library-primary projection ---------------------------------


@pytest.mark.req("FRG-PULL-001")
async def test_current_week_content_and_derived_state_with_no_source(db, tmp_path):
    """No pull source configured at all (`pull_entries` never written): the
    view still lists watched-series issues due this week, each with derived
    state, purely from library + queue records."""
    series_id = await _seed_series(db, tmp_path, title="Saga", cv_volume_id=1)
    missing_id = await _seed_issue(
        db, series_id=series_id, cv_issue_id=101, number="1", store_date=IN_WEEK
    )
    downloaded_id = await _seed_issue(
        db, series_id=series_id, cv_issue_id=102, number="2", store_date=IN_WEEK
    )
    await _add_file(db, downloaded_id, str(tmp_path / "saga-2.cbz"))
    unmonitored_id = await _seed_issue(
        db,
        series_id=series_id,
        cv_issue_id=103,
        number="3",
        store_date=IN_WEEK,
        monitored=False,
    )
    downloading_id = await _seed_issue(
        db, series_id=series_id, cv_issue_id=104, number="4", store_date=IN_WEEK
    )
    await _track(db, issue_id=downloading_id, state=TrackedDownloadState.DOWNLOADING, download_id="d1")
    # Out-of-week issue must not appear.
    await _seed_issue(
        db,
        series_id=series_id,
        cv_issue_id=105,
        number="5",
        store_date=IN_WEEK + dt.timedelta(days=30),
    )

    async with db.read_session() as session:
        entries = await weekly_pull(session, WEEK)

    by_issue = {e.matched_issue_id: e for e in entries}
    assert set(by_issue) == {missing_id, downloaded_id, unmonitored_id, downloading_id}
    assert by_issue[missing_id].state == "missing_wanted"
    assert by_issue[downloaded_id].state == "downloaded"
    assert by_issue[unmonitored_id].state == "unmonitored"
    assert by_issue[downloading_id].state == "downloading"
    # No pull entry backs any of these rows (pure library-primary).
    assert all(e.pull_entry_id is None and e.match_type is None for e in entries)


@pytest.mark.req("FRG-PULL-001")
async def test_no_watched_series_issue_this_week_lists_nothing(db, tmp_path):
    async with db.read_session() as session:
        entries = await weekly_pull(session, WEEK)
    assert entries == []


@pytest.mark.req("FRG-PULL-001")
async def test_adjacent_weeks_navigable_by_parameter(db, tmp_path):
    series_id = await _seed_series(db, tmp_path, title="Saga", cv_volume_id=1)
    prev_id = await _seed_issue(
        db,
        series_id=series_id,
        cv_issue_id=201,
        number="1",
        store_date=dt.date.fromisocalendar(2026, 27, 3),
    )
    current_id = await _seed_issue(
        db, series_id=series_id, cv_issue_id=202, number="2", store_date=IN_WEEK
    )
    next_id = await _seed_issue(
        db,
        series_id=series_id,
        cv_issue_id=203,
        number="3",
        store_date=dt.date.fromisocalendar(2026, 29, 3),
    )

    async with db.read_session() as session:
        prev_entries = await weekly_pull(session, PREV_WEEK)
        current_entries = await weekly_pull(session, WEEK)
        next_entries = await weekly_pull(session, NEXT_WEEK)

    assert {e.matched_issue_id for e in prev_entries} == {prev_id}
    assert {e.matched_issue_id for e in current_entries} == {current_id}
    assert {e.matched_issue_id for e in next_entries} == {next_id}


@pytest.mark.req("FRG-PULL-001")
async def test_view_survives_missing_pull_source_data(db, tmp_path):
    """An empty `pull_entries` table (unconfigured/degraded source) does not
    error and does not empty a week that genuinely has watched-series
    content due — the projection never even queries `pull_entries` for the
    library-primary half."""
    series_id = await _seed_series(db, tmp_path, title="Saga", cv_volume_id=1)
    issue_id = await _seed_issue(
        db, series_id=series_id, cv_issue_id=301, number="1", store_date=IN_WEEK
    )
    async with db.read_session() as session:
        entries = await weekly_pull(session, WEEK)
    assert {e.matched_issue_id for e in entries} == {issue_id}


# --- merge with stored pull entries --------------------------------------------


@pytest.mark.req("FRG-API-019")
async def test_stored_entry_enriches_the_matched_library_row(db, tmp_path):
    series_id = await _seed_series(db, tmp_path, title="Saga", cv_volume_id=1)
    issue_id = await _seed_issue(
        db, series_id=series_id, cv_issue_id=401, number="1", store_date=IN_WEEK
    )
    async with db.write_session() as session:
        rows = await pull_repo.replace_week(
            session,
            WEEK,
            [
                ParsedPullEntry(
                    series_name="Saga",
                    issue_number="1",
                    release_date=IN_WEEK,
                    publisher="Image Comics",
                    cv_series_id=1,
                    cv_issue_id=401,
                )
            ],
        )
        entry_id = rows[0].id
    async with db.write_session() as session:
        await pull_repo.update_match(
            session, entry_id, matched_issue_id=issue_id, match_type="id"
        )

    async with db.read_session() as session:
        entries = await weekly_pull(session, WEEK)

    assert len(entries) == 1
    entry = entries[0]
    assert entry.pull_entry_id == entry_id
    assert entry.matched_issue_id == issue_id
    assert entry.match_type == "id"
    assert entry.publisher == "Image Comics"  # from the stored entry, not the series
    assert entry.state == "missing_wanted"  # still derived from issue+queue


@pytest.mark.req("FRG-API-019")
async def test_unmatched_entry_surfaces_with_no_issue_link_or_state(db):
    async with db.write_session() as session:
        await pull_repo.replace_week(
            session,
            WEEK,
            [
                ParsedPullEntry(
                    series_name="Unknown Comic",
                    issue_number="1",
                    release_date=IN_WEEK,
                    publisher="Some Press",
                )
            ],
        )
    async with db.read_session() as session:
        entries = await weekly_pull(session, WEEK)

    assert len(entries) == 1
    entry = entries[0]
    assert entry.matched_issue_id is None
    assert entry.match_type == "unmatched"
    assert entry.state is None


@pytest.mark.req("FRG-PULL-005")
async def test_matched_but_not_yet_created_entry_is_pending_refresh(db):
    """FRG-PULL-005's "matched a series, issue not created yet" case: the
    matcher (area C) would set `match_type="id"`/"name_seq"` with
    `matched_issue_id` still NULL until `refresh-series` creates the issue."""
    async with db.write_session() as session:
        rows = await pull_repo.replace_week(
            session,
            WEEK,
            [
                ParsedPullEntry(
                    series_name="Saga",
                    issue_number="99",
                    release_date=IN_WEEK,
                    cv_issue_id=999,
                )
            ],
        )
        entry_id = rows[0].id
    async with db.write_session() as session:
        await pull_repo.update_match(
            session, entry_id, matched_issue_id=None, match_type="id"
        )

    async with db.read_session() as session:
        entries = await weekly_pull(session, WEEK)

    assert len(entries) == 1
    assert entries[0].matched_issue_id is None
    assert entries[0].state == "pending_refresh"
