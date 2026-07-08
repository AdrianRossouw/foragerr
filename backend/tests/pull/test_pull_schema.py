"""pull_entries schema round-trips + entry_key determinism (FRG-PULL-003)."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import inspect

from foragerr.pull.models import PullEntryRow, ParsedPullEntry, entry_key
from foragerr.pull import repo


@pytest.mark.req("FRG-PULL-003")
async def test_stored_entry_round_trips_all_typed_fields(db):
    entry = ParsedPullEntry(
        series_name="Saga",
        issue_number="1.5",
        release_date=dt.date(2026, 7, 8),
        publisher="Image",
        cv_series_id=4050,
        cv_issue_id=123456,
    )
    async with db.write_session() as session:
        rows = await repo.replace_week(session, "2026-W28", [entry])
        entry_id = rows[0].id

    async with db.read_session() as session:
        fetched = await session.get(PullEntryRow, entry_id)

    assert fetched.week == "2026-W28"
    assert fetched.publisher == "Image"
    assert fetched.series_name == "Saga"
    assert fetched.issue_number == "1.5"  # verbatim, no numeric coercion
    assert fetched.cv_series_id == 4050
    assert fetched.cv_issue_id == 123456
    assert fetched.release_date == dt.date(2026, 7, 8)
    assert fetched.matched_issue_id is None
    assert fetched.match_type == "unmatched"
    assert fetched.fetched_at is not None
    assert fetched.entry_key == "cv:123456"  # id-preferred derivation


@pytest.mark.req("FRG-PULL-003")
async def test_entry_key_prefers_cv_issue_id(db):
    a = ParsedPullEntry(
        series_name="Saga",
        issue_number="1",
        release_date=dt.date(2026, 7, 8),
        publisher="Image",
        cv_issue_id=999,
    )
    b = ParsedPullEntry(
        series_name="A Completely Different Title",
        issue_number="99",
        release_date=dt.date(1999, 1, 1),
        publisher="Someone Else",
        cv_issue_id=999,
    )
    assert entry_key(a) == entry_key(b) == "cv:999"


@pytest.mark.req("FRG-PULL-003")
def test_entry_key_name_fallback_is_stable_across_incidental_drift():
    """Same logical source row (name/number/publisher), differing only in
    whitespace/case, yields the same key when no cv_issue_id is supplied —
    this is what makes a re-fetch idempotent for id-less source rows."""
    canonical = ParsedPullEntry(
        series_name="East of West",
        issue_number="12",
        release_date=dt.date(2026, 7, 8),
        publisher="Image",
    )
    noisy = ParsedPullEntry(
        series_name="  east of west  ",
        issue_number="12",
        release_date=dt.date(2026, 7, 8),
        publisher="IMAGE",
    )
    assert entry_key(canonical) == entry_key(noisy)


@pytest.mark.req("FRG-PULL-003")
def test_entry_key_name_fallback_distinguishes_different_logical_rows():
    one = ParsedPullEntry(
        series_name="East of West", issue_number="12", release_date=dt.date(2026, 7, 8)
    )
    two = ParsedPullEntry(
        series_name="East of West", issue_number="13", release_date=dt.date(2026, 7, 8)
    )
    assert entry_key(one) != entry_key(two)


@pytest.mark.req("FRG-PULL-003")
async def test_no_wanted_or_status_column_exists_on_pull_entries(db):
    """Schema-inventory guard mirroring `library.models`' `wanted` guard: the
    D4 invariant is that pull entries carry only a link (`matched_issue_id`)
    + `match_type` discriminator, never a wanted/downloaded/skipped status of
    their own."""

    def _column_names(sync_conn) -> set[str]:
        inspector = inspect(sync_conn)
        return {col["name"].lower() for col in inspector.get_columns("pull_entries")}

    async with db.engine.connect() as conn:
        names = await conn.run_sync(_column_names)

    forbidden = {"wanted", "is_wanted", "wanted_status", "status", "downloaded", "skipped"}
    assert not (names & forbidden), f"pull_entries exposes a status-shaped column: {names}"
    assert {"matched_issue_id", "match_type"} <= names


@pytest.mark.req("FRG-PULL-003")
async def test_mistyped_bind_rejected_for_typed_columns(db):
    """FRG-DB-008: the strict types reject a mistyped bind at the persistence
    layer rather than letting SQLite silently coerce it."""
    from sqlalchemy.exc import StatementError

    bad = ParsedPullEntry(
        series_name="Saga",
        issue_number=1.5,  # not a str — IssueNumberText must reject this
        release_date=dt.date(2026, 7, 8),
        cv_issue_id=555,  # short-circuits entry_key's id-preferred path so
        # the mistyped issue_number reaches the persistence layer untouched
    )
    with pytest.raises(StatementError):
        async with db.write_session() as session:
            await repo.replace_week(session, "2026-W28", [bad])
