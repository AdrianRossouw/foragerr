"""repo.replace_week: per-week idempotent replace-on-refresh (FRG-PULL-003)."""

from __future__ import annotations

import datetime as dt

import pytest

from foragerr.pull import repo
from foragerr.pull.models import ParsedPullEntry, PullEntryRow

WEEK_A = "2026-W28"
WEEK_B = "2026-W29"


def _entries(*, issue_numbers: list[str]) -> list[ParsedPullEntry]:
    return [
        ParsedPullEntry(
            series_name="Saga",
            issue_number=number,
            release_date=dt.date(2026, 7, 8),
            publisher="Image",
            cv_issue_id=1000 + i,
        )
        for i, number in enumerate(issue_numbers)
    ]


async def _week_rows(db, week: str) -> list[PullEntryRow]:
    async with db.read_session() as session:
        return await repo.list_week(session, week)


@pytest.mark.req("FRG-PULL-003")
async def test_refetching_a_week_is_idempotent(db):
    first = _entries(issue_numbers=["1", "2", "3"])
    async with db.write_session() as session:
        await repo.replace_week(session, WEEK_A, first)

    before = sorted((r.entry_key, r.issue_number, r.cv_issue_id) for r in await _week_rows(db, WEEK_A))

    # A second fetch of the SAME logical week (same source rows, re-derived).
    second = _entries(issue_numbers=["1", "2", "3"])
    async with db.write_session() as session:
        await repo.replace_week(session, WEEK_A, second)

    after = sorted((r.entry_key, r.issue_number, r.cv_issue_id) for r in await _week_rows(db, WEEK_A))

    assert before == after
    assert len(after) == 3


@pytest.mark.req("FRG-PULL-003")
async def test_replace_week_never_touches_other_weeks(db):
    async with db.write_session() as session:
        await repo.replace_week(session, WEEK_A, _entries(issue_numbers=["1"]))
        await repo.replace_week(session, WEEK_B, _entries(issue_numbers=["1", "2"]))

    # Re-fetch only week A with a shrunk set.
    async with db.write_session() as session:
        await repo.replace_week(session, WEEK_A, [])

    assert await _week_rows(db, WEEK_A) == []
    assert len(await _week_rows(db, WEEK_B)) == 2  # untouched by week A's replace


@pytest.mark.req("FRG-PULL-003")
async def test_stored_entries_carry_source_cv_ids(db):
    entries = [
        ParsedPullEntry(
            series_name="Saga",
            issue_number="1",
            release_date=dt.date(2026, 7, 8),
            publisher="Image",
            cv_series_id=4050,
            cv_issue_id=123456,
        )
    ]
    async with db.write_session() as session:
        await repo.replace_week(session, WEEK_A, entries)

    rows = await _week_rows(db, WEEK_A)
    assert rows[0].cv_series_id == 4050
    assert rows[0].cv_issue_id == 123456


@pytest.mark.req("FRG-PULL-003")
async def test_a_failed_replace_does_not_half_replace_the_week(db):
    """Simulates a mid-run failure (a malformed fetched batch that collides
    on entry_key) inside the SAME write transaction as the replace: the
    delete already issued against the session must roll back along with the
    failed insert, leaving the prior week's rows byte-for-byte intact."""
    original = _entries(issue_numbers=["1", "2", "3"])
    async with db.write_session() as session:
        await repo.replace_week(session, WEEK_A, original)

    before = sorted(
        (r.entry_key, r.issue_number, r.cv_issue_id, r.publisher)
        for r in await _week_rows(db, WEEK_A)
    )

    # Two entries that collide on entry_key (same cv_issue_id) — this must
    # blow up the insert with a unique-constraint violation partway through
    # the batch, simulating a mid-fetch failure.
    colliding = [
        ParsedPullEntry(
            series_name="Saga", issue_number="1", release_date=dt.date(2026, 7, 8), cv_issue_id=9,
        ),
        ParsedPullEntry(
            series_name="Saga", issue_number="1", release_date=dt.date(2026, 7, 8), cv_issue_id=9,
        ),
    ]
    with pytest.raises(Exception):
        async with db.write_session() as session:
            await repo.replace_week(session, WEEK_A, colliding)

    after = sorted(
        (r.entry_key, r.issue_number, r.cv_issue_id, r.publisher)
        for r in await _week_rows(db, WEEK_A)
    )
    assert before == after  # the prior week survived the failed replace intact
    assert len(after) == 3


@pytest.mark.req("FRG-PULL-003")
async def test_replace_week_composes_into_a_larger_caller_transaction(db):
    """`replace_week` never commits/rolls back itself — a caller can compose
    it with other writes inside one `write_session()` block and have both
    halves succeed or fail together (the shape D's `pull-refresh` command
    needs for fetch+store+match in one commit)."""
    from foragerr.library import repo as library_repo

    async with db.write_session() as session:
        await repo.replace_week(session, WEEK_A, _entries(issue_numbers=["1"]))
        rf = await library_repo.create_root_folder(session, "/tmp/does-not-matter-pull-compose")

    async with db.read_session() as session:
        rows = await repo.list_week(session, WEEK_A)
        fetched_rf = await session.get(type(rf), rf.id)
    assert len(rows) == 1
    assert fetched_rf is not None


@pytest.mark.req("FRG-PULL-003")
async def test_update_match_writes_only_the_link_and_match_type(db, seed_series_issue_ids):
    series_id, issue_id = seed_series_issue_ids
    async with db.write_session() as session:
        rows = await repo.replace_week(session, WEEK_A, _entries(issue_numbers=["1"]))
        entry_id = rows[0].id

    async with db.write_session() as session:
        await repo.update_match(session, entry_id, matched_issue_id=issue_id, match_type="id")

    async with db.read_session() as session:
        fetched = await session.get(PullEntryRow, entry_id)
    assert fetched.matched_issue_id == issue_id
    assert fetched.match_type == "id"
    # untouched fields:
    assert fetched.series_name == "Saga"
    assert fetched.issue_number == "1"
