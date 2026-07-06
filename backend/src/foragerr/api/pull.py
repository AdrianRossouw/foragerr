"""The pull HTTP surface: ``GET /api/v1/pull`` (FRG-API-019).

Read-only projection of the weekly pull view (FRG-PULL-001) merged with any
stored pull entries (FRG-PULL-003) — see :mod:`foragerr.pull.projection` for
the merge itself. This module owns only the HTTP shape: paging/sort over the
in-memory projected list (a bounded, week-scoped set — single-user scale, per
design §Risks), the uniform paging envelope (FRG-API-002/FRG-API-006), and the
camelCase wire resource. It exposes no secret (no provider key, credential, or
raw source URL) and performs no write of any kind — the only refresh path is
the existing task force-run (`POST /api/v1/system/task/pull-refresh`,
FRG-API-014 / FRG-SCHED-007), not this router.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Callable

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from foragerr.api.errors import ApiError
from foragerr.api.paging import envelope, load_issue_map, load_series_map
from foragerr.pull.projection import (
    MalformedWeek,
    ProjectedPullEntry,
    current_week,
    weekly_pull,
)

router = APIRouter(prefix="/pull", tags=["pull"])

_SORT_DIRECTIONS = ("asc", "desc")

#: Sort keys are whitelisted to a fixed Python key function over
#: `ProjectedPullEntry` — mirrors `api/paging.py`'s SQL-column whitelist
#: pattern, just evaluated in memory rather than as an ORDER BY (the
#: projection merges two separate queries, so there is no single `Select` to
#: sort in SQL). An unknown key is a 400 naming the field, never a silent
#: default or a 500 — same contract as every other paged endpoint.
_SORT_KEYS: dict[str, Callable[[ProjectedPullEntry], Any]] = {
    "release_date": lambda e: (
        e.release_date is None,
        e.release_date or dt.date.min,
        e.series_name,
        e.issue_number or "",
    ),
    "series_name": lambda e: (
        e.series_name,
        e.release_date is None,
        e.release_date or dt.date.min,
    ),
}


class PullSeries(BaseModel):
    id: int
    title: str


class PullIssue(BaseModel):
    id: int
    issueNumber: str | None
    title: str | None


class PullEntryResource(BaseModel):
    """One weekly pull row (FRG-API-019).

    ``id`` is the stored ``pull_entries`` row id when one exists, and
    ``None`` for a pure library-primary row with no corresponding stored
    entry (no pull source configured/degraded). ``state`` is the linked
    issue's derived state (`missing_wanted` / `downloading` / `downloaded` /
    `unmonitored`), `pending_refresh` for a matched-but-not-yet-created
    entry, or `None` for an unmatched/new-series entry with no issue link.
    """

    id: int | None
    week: str
    publisher: str | None
    seriesName: str
    issueNumber: str | None
    releaseDate: dt.date | None
    cvSeriesId: int | None
    cvIssueId: int | None
    matchType: str | None
    matchedIssueId: int | None
    state: str | None
    series: PullSeries | None
    issue: PullIssue | None


class PullPage(BaseModel):
    """Paging envelope (FRG-API-002) specialized for pull resources."""

    page: int
    pageSize: int
    sortKey: str
    sortDirection: str
    totalRecords: int
    records: list[PullEntryResource]


def _to_resource(entry: ProjectedPullEntry, issue, series) -> PullEntryResource:
    return PullEntryResource(
        id=entry.pull_entry_id,
        week=entry.week,
        publisher=entry.publisher,
        seriesName=entry.series_name,
        issueNumber=entry.issue_number,
        releaseDate=entry.release_date,
        cvSeriesId=entry.cv_series_id,
        cvIssueId=entry.cv_issue_id,
        matchType=entry.match_type,
        matchedIssueId=entry.matched_issue_id,
        state=entry.state,
        series=PullSeries(id=series.id, title=series.title) if series else None,
        issue=(
            PullIssue(id=issue.id, issueNumber=issue.issue_number, title=issue.title)
            if issue
            else None
        ),
    )


@router.get("", response_model=PullPage)
async def get_pull(
    request: Request,
    week: str | None = Query(None),
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=200),
    sortKey: str = Query("release_date"),
    sortDirection: str = Query("asc"),
) -> PullPage:
    """Paged weekly pull projection (FRG-API-019).

    ``week`` omitted defaults to the current ISO store-date week (FRG-PULL-001
    scenario: "omitted week defaults to the current week"); an arbitrary week
    is accepted so prev/current/next navigation is three client calls with no
    server-side navigation state (design §8). A malformed ``week`` is a 400
    naming the field — never a 500, never a silently-empty page mistaken for
    "nothing this week". Read-only: this handler issues no write of any kind.
    """
    if sortDirection not in _SORT_DIRECTIONS:
        raise ApiError(
            400,
            f"sortDirection must be one of {_SORT_DIRECTIONS} (got {sortDirection!r})",
            field="sortDirection",
        )
    key_fn = _SORT_KEYS.get(sortKey)
    if key_fn is None:
        raise ApiError(
            400,
            f"unknown sortKey {sortKey!r}; must be one of {sorted(_SORT_KEYS)}",
            field="sortKey",
        )

    target_week = week if week is not None else current_week()

    db = request.app.state.db
    async with db.read_session() as session:
        try:
            entries = await weekly_pull(session, target_week)
        except MalformedWeek as exc:
            raise ApiError(400, str(exc), field="week") from exc

        entries.sort(key=key_fn, reverse=(sortDirection == "desc"))
        total = len(entries)
        start = (page - 1) * pageSize
        page_entries = entries[start : start + pageSize]

        issue_ids = {e.matched_issue_id for e in page_entries if e.matched_issue_id is not None}
        issue_by_id = await load_issue_map(session, issue_ids)
        series_ids = {e.series_id for e in page_entries if e.series_id is not None}
        series_by_id = await load_series_map(session, series_ids)

        records = [
            _to_resource(
                e,
                issue_by_id.get(e.matched_issue_id),
                series_by_id.get(e.series_id),
            )
            for e in page_entries
        ]

    result = envelope(
        page=page,
        page_size=pageSize,
        sort_key=sortKey,
        sort_direction=sortDirection,
        total_records=total,
        records=records,
    )
    return PullPage(**result)


__all__ = ["router"]
