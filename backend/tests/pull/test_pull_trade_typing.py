"""The pull-matcher arm of the trade-typing invariant (FRG-SER-019).

A series' collected-edition `booktype` is a DISTINCT field from the issue-level
`issue_type` the pull matcher's book-type guard reads (`pull/matching.py`).
Typing a series as a trade must therefore leave pull matching unaffected: the
guard still resolves the typed line's entries by the issue's own `issue_type`,
never the series' `booktype`. This pins that they do not cross.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from sqlalchemy import select

from foragerr.library import repo as lib_repo
from foragerr.library.models import SeriesRow
from foragerr.pull import matching, repo
from foragerr.pull.models import ParsedPullEntry
from foragerr.quality.models import DEFAULT_PROFILE_NAME, FormatProfileRow

WEEK = "2026-W28"
RELEASE = dt.date(2026, 7, 8)


async def _seed(db, root: Path, specs: list[dict]) -> None:
    """Watched series + issues, each optionally trade-typed via ``booktype``."""
    root.mkdir(exist_ok=True)
    async with db.read_session() as session:
        profile_id = (
            await session.execute(
                select(FormatProfileRow.id).where(FormatProfileRow.name == DEFAULT_PROFILE_NAME)
            )
        ).scalar_one()
    async with db.write_session() as session:
        rf = await lib_repo.create_root_folder(session, str(root))
        for spec in specs:
            series = await lib_repo.create_series(
                session,
                cv_volume_id=spec["cv_volume_id"],
                title=spec["title"],
                format_profile_id=profile_id,
                root_folder_id=rf.id,
                path=str(root / spec["title"]),
            )
            series.booktype = spec.get("booktype")  # the trade typing under test
            for iss in spec.get("issues", []):
                await lib_repo.create_issue(
                    session,
                    series_id=series.id,
                    cv_issue_id=iss["cv_issue_id"],
                    issue_number=iss["number"],
                    issue_type=iss.get("issue_type", "regular"),
                    monitored=True,
                )
            await session.flush()


async def _match(db, entries: list[ParsedPullEntry]) -> list[matching.MatchResult]:
    async with db.write_session() as session:
        rows = await repo.replace_week(session, WEEK, entries)
        return await matching.match_week(session, rows)


@pytest.mark.req("FRG-SER-019")
async def test_pull_id_match_still_works_for_a_trade_typed_series(db, tmp_path):
    """A trade-typed series whose issue is a REGULAR issue still id-matches a
    regular pull entry — the series `booktype='tpb'` does not feed the guard."""
    await _seed(
        db,
        tmp_path / "lib",
        [{"title": "Saga", "cv_volume_id": 10, "booktype": "tpb",
          "issues": [{"number": "1", "cv_issue_id": 5000, "issue_type": "regular"}]}],
    )
    [result] = await _match(
        db,
        [ParsedPullEntry(series_name="Saga", issue_number="1", release_date=RELEASE, cv_issue_id=5000)],
    )
    assert result.match_type == "id"
    assert result.matched_issue_id is not None


@pytest.mark.req("FRG-SER-019")
async def test_pull_book_type_guard_unchanged_by_series_typing(db, tmp_path):
    """The issue-level book-type guard's behaviour is identical whether or not
    the series carries a collected-edition `booktype`: a regular entry matches
    a regular issue, and rejects an annual issue — series typing changes
    neither outcome."""
    await _seed(
        db,
        tmp_path / "lib",
        [
            {"title": "Spawn", "cv_volume_id": 10, "booktype": "tpb", "issues": [
                {"number": "1", "cv_issue_id": 5000, "issue_type": "regular"}]},
            {"title": "Batman", "cv_volume_id": 20, "booktype": "hc", "issues": [
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
    # Regular entry -> regular issue: still links despite the series typing.
    assert control.match_type == "id" and control.matched_issue_id is not None
    # Regular entry -> annual issue: still rejected by the (issue-level) guard.
    assert guarded.match_type == "unmatched" and guarded.matched_issue_id is None
