"""Guarded pull-entry → library matcher (FRG-PULL-004).

Every delta scenario as an explicit acceptance fixture: id match (happy +
book-type guard + lying-cv-id), guarded name match (happy + each guard
rejecting individually + alias), unmatched-never-guessed, new-series tagging,
the delta's headline mixed week, and the D4 link-only write shape.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from sqlalchemy import func, select

from foragerr.library import repo as lib_repo
from foragerr.library.models import IssueRow, SeriesRow
from foragerr.pull import matching, repo
from foragerr.pull.models import ParsedPullEntry, PullEntryRow
from foragerr.quality.models import DEFAULT_PROFILE_NAME, FormatProfileRow

WEEK = "2026-W28"
# The pull week's release date every entry is filed under, unless overridden.
RELEASE = dt.date(2026, 7, 8)


async def _seed(db, root: Path, series_specs: list[dict]) -> dict[str, int]:
    """Create watched series + issues; return ``{series_title: series_id}``.

    Each spec: ``{title, aliases?, cv_volume_id, issues=[{number, cv_issue_id,
    store_date?, issue_type?}]}``.
    """
    root.mkdir(exist_ok=True)
    async with db.read_session() as session:
        profile_id = (
            await session.execute(
                select(FormatProfileRow.id).where(FormatProfileRow.name == DEFAULT_PROFILE_NAME)
            )
        ).scalar_one()
    ids: dict[str, int] = {}
    async with db.write_session() as session:
        rf = await lib_repo.create_root_folder(session, str(root))
        for spec in series_specs:
            series = await lib_repo.create_series(
                session,
                cv_volume_id=spec["cv_volume_id"],
                title=spec["title"],
                format_profile_id=profile_id,
                root_folder_id=rf.id,
                path=str(root / spec["title"]),
                monitored=spec.get("monitored", True),
            )
            await session.flush()
            if spec.get("aliases"):
                from foragerr.library.flows import encode_aliases

                series.aliases = encode_aliases(spec["aliases"])
            for iss in spec.get("issues", []):
                await lib_repo.create_issue(
                    session,
                    series_id=series.id,
                    cv_issue_id=iss["cv_issue_id"],
                    issue_number=iss["number"],
                    store_date=iss.get("store_date"),
                    issue_type=iss.get("issue_type", "regular"),
                    monitored=True,
                )
            await session.flush()
            ids[spec["title"]] = series.id
    return ids


async def _match(db, entries: list[ParsedPullEntry]) -> list[matching.MatchResult]:
    async with db.write_session() as session:
        rows = await repo.replace_week(session, WEEK, entries)
        return await matching.match_week(session, rows)


async def _rows(db) -> list[PullEntryRow]:
    async with db.read_session() as session:
        return await repo.list_week(session, WEEK)


# --- ID match -----------------------------------------------------------------


@pytest.mark.req("FRG-PULL-004")
async def test_id_match_links_on_verified_candidate(db, tmp_path):
    await _seed(
        db,
        tmp_path / "lib",
        [{"title": "Spawn", "cv_volume_id": 10, "issues": [{"number": "350", "cv_issue_id": 5000}]}],
    )
    [result] = await _match(
        db,
        [ParsedPullEntry(series_name="Spawn", issue_number="350", release_date=RELEASE, cv_issue_id=5000)],
    )
    assert result.match_type == "id"
    assert result.matched_issue_id is not None
    # Persisted onto the row, not just returned.
    [row] = await _rows(db)
    assert row.match_type == "id" and row.matched_issue_id == result.matched_issue_id


@pytest.mark.req("FRG-PULL-004")
async def test_unmonitored_series_is_not_matched(db, tmp_path):
    """The matcher indexes only *watched* (monitored) series (FRG-PULL-005): a
    pull entry for a paused series must not link to it, or the refresh trigger
    would enqueue refresh-series work the monitored-scoped weekly view never
    surfaces. Same fixture as the id-match case but the series is unmonitored."""
    await _seed(
        db,
        tmp_path / "lib",
        [{"title": "Spawn", "cv_volume_id": 10, "monitored": False,
          "issues": [{"number": "350", "cv_issue_id": 5000}]}],
    )
    [result] = await _match(
        db,
        [ParsedPullEntry(series_name="Spawn", issue_number="350", release_date=RELEASE, cv_issue_id=5000)],
    )
    assert result.matched_series_id is None  # no trigger fires for a paused series
    assert result.matched_issue_id is None
    assert result.match_type in {"unmatched", "new_series"}


@pytest.mark.req("FRG-PULL-004")
async def test_book_type_guard_rejects_id_match_to_wrong_book_type(db, tmp_path):
    # Two entries with identical id-resolution mechanics that differ ONLY in the
    # resolved library issue's book-type, so the guard is the sole variable:
    #   - Spawn: id resolves to a REGULAR issue → links (control).
    #   - Batman: id resolves to an ANNUAL issue while the entry is a regular
    #     issue → the book-type guard rejects the id; the fallthrough name match
    #     also fails (delta 8), so it stays unmatched.
    await _seed(
        db,
        tmp_path / "lib",
        [
            {"title": "Spawn", "cv_volume_id": 10, "issues": [
                {"number": "1", "cv_issue_id": 5000, "issue_type": "regular"}]},
            {"title": "Batman", "cv_volume_id": 20, "issues": [
                {"number": "1", "cv_issue_id": 6000, "issue_type": "annual"}]},
        ],
    )
    control, guarded = await _match(
        db,
        [
            ParsedPullEntry(series_name="Spawn", issue_number="1", release_date=RELEASE, cv_issue_id=5000),
            ParsedPullEntry(series_name="Batman", issue_number="9", release_date=RELEASE, cv_issue_id=6000),
        ],
    )
    assert control.match_type == "id" and control.matched_issue_id is not None
    assert guarded.match_type == "unmatched" and guarded.matched_issue_id is None


@pytest.mark.req("FRG-PULL-004")
async def test_id_that_lies_about_its_series_is_not_trusted(db, tmp_path):
    # The source cv_issue_id points at Spawn's issue, but the entry names Saga
    # (a different watched series). The candidate id is verified against library
    # metadata and rejected — it never links the entry to Spawn.
    await _seed(
        db,
        tmp_path / "lib",
        [
            {"title": "Spawn", "cv_volume_id": 10, "issues": [{"number": "1", "cv_issue_id": 5000}]},
            {"title": "Saga", "cv_volume_id": 20, "issues": [{"number": "2", "cv_issue_id": 6000}]},
        ],
    )
    # Saga latest is #2; entry #5 fails the sequence guard too → plain unmatched.
    [result] = await _match(
        db,
        [ParsedPullEntry(series_name="Saga", issue_number="5", release_date=RELEASE, cv_issue_id=5000)],
    )
    assert result.match_type == "unmatched"
    assert result.matched_issue_id is None


# --- guarded NAME match -------------------------------------------------------


@pytest.mark.req("FRG-PULL-004")
async def test_name_match_links_when_all_guards_hold(db, tmp_path):
    await _seed(
        db,
        tmp_path / "lib",
        [{"title": "Saga", "cv_volume_id": 20, "issues": [
            {"number": "10", "cv_issue_id": 6000, "store_date": dt.date(2026, 7, 7)},
        ]}],
    )
    # No cv id → name path. delta 0 (matches existing #10), date +1 day (≤ ±2).
    [result] = await _match(
        db,
        [ParsedPullEntry(series_name="Saga", issue_number="10", release_date=RELEASE)],
    )
    assert result.match_type == "name_seq"
    assert result.matched_issue_id is not None
    assert result.matched_series_id is not None


@pytest.mark.req("FRG-PULL-004")
async def test_name_match_future_issue_is_matched_but_missing(db, tmp_path):
    # A plausible next-in-sequence issue not yet in the library: name_seq match
    # to the series, but matched_issue_id stays None (area D queues a refresh).
    ids = await _seed(
        db,
        tmp_path / "lib",
        [{"title": "Saga", "cv_volume_id": 20, "issues": [{"number": "10", "cv_issue_id": 6000}]}],
    )
    [result] = await _match(
        db,
        [ParsedPullEntry(series_name="Saga", issue_number="11", release_date=RELEASE)],
    )
    assert result.match_type == "name_seq"
    assert result.matched_issue_id is None
    assert result.matched_series_id == ids["Saga"]


@pytest.mark.req("FRG-PULL-004")
async def test_name_match_rejected_when_release_date_outside_pull_week(db, tmp_path):
    # A sequence-plausible MISSING issue (delta 1, no local issue to date-check)
    # whose ship date is nowhere near the stored pull week must be rejected by the
    # week window (FRG-PULL-004 "release date within the pull week ±2 days") — else
    # it would name_seq-match and wrongly enqueue refresh-series. WEEK is 2026-W28.
    ids = await _seed(
        db,
        tmp_path / "lib",
        [{"title": "Saga", "cv_volume_id": 20, "issues": [{"number": "10", "cv_issue_id": 6000}]}],
    )
    [result] = await _match(
        db,
        [ParsedPullEntry(series_name="Saga", issue_number="11", release_date=dt.date(2027, 1, 1))],
    )
    assert result.match_type == "unmatched"
    assert result.matched_issue_id is None
    assert result.matched_series_id is None


@pytest.mark.req("FRG-PULL-004")
async def test_name_match_rejected_when_sequence_delta_too_large(db, tmp_path):
    await _seed(
        db,
        tmp_path / "lib",
        [{"title": "Saga", "cv_volume_id": 20, "issues": [{"number": "10", "cv_issue_id": 6000}]}],
    )
    # delta 4 (10 → 14) is outside 0 ≤ delta < 3.
    [result] = await _match(
        db,
        [ParsedPullEntry(series_name="Saga", issue_number="14", release_date=RELEASE)],
    )
    assert result.match_type == "unmatched"
    assert result.matched_issue_id is None


@pytest.mark.req("FRG-PULL-004")
async def test_name_match_rejected_when_date_outside_window(db, tmp_path):
    # Existing #11 dated 3 days off the entry's release → date guard rejects,
    # even though name + sequence (delta 0) pass.
    await _seed(
        db,
        tmp_path / "lib",
        [{"title": "Saga", "cv_volume_id": 20, "issues": [
            {"number": "11", "cv_issue_id": 6000, "store_date": RELEASE + dt.timedelta(days=3)},
        ]}],
    )
    [result] = await _match(
        db,
        [ParsedPullEntry(series_name="Saga", issue_number="11", release_date=RELEASE)],
    )
    assert result.match_type == "unmatched"
    assert result.matched_issue_id is None


@pytest.mark.req("FRG-PULL-004")
async def test_name_match_via_registered_alias(db, tmp_path):
    await _seed(
        db,
        tmp_path / "lib",
        [{"title": "The Savage Dragon", "cv_volume_id": 30, "aliases": ["Savage Dragon"],
          "issues": [{"number": "5", "cv_issue_id": 7000, "store_date": RELEASE}]}],
    )
    # Entry names the alias, not the title.
    [result] = await _match(
        db,
        [ParsedPullEntry(series_name="Savage Dragon", issue_number="5", release_date=RELEASE)],
    )
    assert result.match_type == "name_seq"
    assert result.matched_issue_id is not None


@pytest.mark.req("FRG-PULL-004")
async def test_wrong_volume_collision_stays_unmatched_never_guessed(db, tmp_path):
    # Same normalized name + same number, but the library issue is a different
    # volume dated years earlier: the date guard leaves it unmatched rather than
    # guessing a link. The series IS in the library, so it is NOT new_series.
    await _seed(
        db,
        tmp_path / "lib",
        [{"title": "Nailbiter", "cv_volume_id": 40, "issues": [
            {"number": "1", "cv_issue_id": 8000, "store_date": dt.date(2013, 5, 1)},
        ]}],
    )
    [result] = await _match(
        db,
        [ParsedPullEntry(series_name="Nailbiter", issue_number="1", release_date=RELEASE)],
    )
    assert result.match_type == "unmatched"
    assert result.matched_issue_id is None


# --- new-series tagging -------------------------------------------------------


@pytest.mark.req("FRG-PULL-004")
async def test_unmatched_new_number_one_tagged_new_series_no_series_created(db, tmp_path):
    await _seed(db, tmp_path / "lib", [{"title": "Spawn", "cv_volume_id": 10}])
    async with db.read_session() as session:
        before = (await session.execute(select(func.count()).select_from(SeriesRow))).scalar_one()

    [result] = await _match(
        db,
        [ParsedPullEntry(series_name="Brand New Comic", issue_number="1", release_date=RELEASE)],
    )
    assert result.match_type == "new_series"
    assert result.matched_issue_id is None
    assert result.matched_series_id is None

    async with db.read_session() as session:
        after = (await session.execute(select(func.count()).select_from(SeriesRow))).scalar_one()
    assert after == before  # tagged only — no series record created


@pytest.mark.req("FRG-PULL-004")
async def test_unknown_series_non_debut_is_plain_unmatched(db, tmp_path):
    await _seed(db, tmp_path / "lib", [{"title": "Spawn", "cv_volume_id": 10}])
    [result] = await _match(
        db,
        [ParsedPullEntry(series_name="Brand New Comic", issue_number="7", release_date=RELEASE)],
    )
    assert result.match_type == "unmatched"  # #7 is not a #1/#0 debut


# --- the delta's headline mixed week ------------------------------------------


@pytest.mark.req("FRG-PULL-004")
async def test_mixed_week_produces_exactly_the_guarded_links(db, tmp_path):
    await _seed(
        db,
        tmp_path / "lib",
        [
            # (a) id-match target
            {"title": "Spawn", "cv_volume_id": 10, "issues": [
                {"number": "350", "cv_issue_id": 5000, "store_date": RELEASE}]},
            # (b) name+sequence target within the date window
            {"title": "Saga", "cv_volume_id": 20, "issues": [
                {"number": "60", "cv_issue_id": 6000, "store_date": dt.date(2026, 7, 7)}]},
            # (c) wrong-volume collision: same name+number, far-off date
            {"title": "Nailbiter", "cv_volume_id": 40, "issues": [
                {"number": "1", "cv_issue_id": 8000, "store_date": dt.date(2013, 5, 1)}]},
        ],
    )
    entries = [
        # (a) valid id match
        ParsedPullEntry(series_name="Spawn", issue_number="350", release_date=RELEASE, cv_issue_id=5000),
        # (b) valid name match (delta 0, date +1 day)
        ParsedPullEntry(series_name="Saga", issue_number="60", release_date=RELEASE),
        # (c) wrong-volume collision → rejected
        ParsedPullEntry(series_name="Nailbiter", issue_number="1", release_date=RELEASE),
        # (d) unknown series → unmatched (a #4, not a debut)
        ParsedPullEntry(series_name="Totally Unknown", issue_number="4", release_date=RELEASE),
    ]
    results = await _match(db, entries)
    linked = [r for r in results if r.matched_issue_id is not None]
    unmatched = [r for r in results if r.match_type == "unmatched"]
    assert len(linked) == 2  # exactly a and b
    assert len(unmatched) == 2  # exactly c and d
    assert {r.match_type for r in linked} == {"id", "name_seq"}


# --- D4: link-only writes -----------------------------------------------------


@pytest.mark.req("FRG-PULL-004")
async def test_match_writes_only_link_and_type_never_status(db, tmp_path):
    # The entry table carries no status-shaped column at all (D4 invariant).
    columns = set(PullEntryRow.__table__.columns.keys())
    assert not (columns & {"status", "wanted", "downloaded", "skipped", "monitored"})

    await _seed(
        db,
        tmp_path / "lib",
        [{"title": "Spawn", "cv_volume_id": 10, "issues": [
            {"number": "350", "cv_issue_id": 5000, "store_date": RELEASE}]}],
    )
    entry = ParsedPullEntry(
        series_name="Spawn", issue_number="350", release_date=RELEASE, publisher="Image", cv_issue_id=5000
    )
    async with db.write_session() as session:
        [row] = await repo.replace_week(session, WEEK, [entry])
        before = (row.series_name, row.issue_number, row.release_date, row.cv_issue_id, row.publisher, row.week)
        await matching.match_week(session, [row])

    [row] = await _rows(db)
    after = (row.series_name, row.issue_number, row.release_date, row.cv_issue_id, row.publisher, row.week)
    assert row.match_type == "id" and row.matched_issue_id is not None  # link + type set
    assert before == after  # every fetched field untouched by the match phase
