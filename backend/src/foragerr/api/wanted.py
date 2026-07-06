"""The wanted/missing HTTP surface: ``GET /api/v1/wanted/missing`` (FRG-API-012).

DERIVED at query time from :func:`foragerr.library.repo.wanted_issues` — the
exact SELECT the backlog search walks (``search_ops.commands``), so this screen
and the search can never disagree about what is missing. There is no stored
wanted status anywhere (deliberate divergence from Mylar, FRG-SER-004):
importing a file removes an issue from this list purely by inserting its
``issue_files`` row, and deleting the file returns it. No cutoff-unmet surface
exists (quality cutoffs are parked outside M2/M3).
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from sqlalchemy import func

from foragerr.api.history import load_series_map
from foragerr.api.paging import paginate
from foragerr.library.models import IssueRow, SeriesRow
from foragerr.library.repo import wanted_issues

router = APIRouter(prefix="/wanted", tags=["wanted"])

#: Release date prefers the actual on-sale date and falls back to the cover
#: date — the same preference the wanted query's "released" predicate uses.
_RELEASE_DATE = func.coalesce(IssueRow.store_date, IssueRow.cover_date)

_SORT_WHITELIST = {
    "release_date": _RELEASE_DATE,
    #: Cheap: `wanted_issues()` already joins `series`.
    "series_title": SeriesRow.sort_title,
}


class WantedSeries(BaseModel):
    id: int
    title: str


class WantedIssueResource(BaseModel):
    """One missing issue, mirroring the issues API's field shapes (FRG-API-012).

    ``issue_number`` stays a verbatim string (never int/float — FRG-SER-002);
    no file fields exist because a wanted issue BY DEFINITION has none.
    """

    id: int
    series_id: int
    cv_issue_id: int
    issue_number: str | None
    title: str | None
    cover_date: dt.date | None
    store_date: dt.date | None
    issue_type: str
    monitored: bool
    series: WantedSeries | None


class WantedPage(BaseModel):
    """Paging envelope (FRG-API-002) specialized for wanted issues."""

    page: int
    pageSize: int
    sortKey: str
    sortDirection: str
    totalRecords: int
    records: list[WantedIssueResource]


def _to_resource(row: IssueRow, series: SeriesRow | None) -> WantedIssueResource:
    return WantedIssueResource(
        id=row.id,
        series_id=row.series_id,
        cv_issue_id=row.cv_issue_id,
        issue_number=row.issue_number,
        title=row.title,
        cover_date=row.cover_date,
        store_date=row.store_date,
        issue_type=row.issue_type,
        monitored=row.monitored,
        series=WantedSeries(id=series.id, title=series.title) if series else None,
    )


@router.get("/missing", response_model=WantedPage)
async def list_missing(
    request: Request,
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=200),
    sortKey: str = Query("release_date"),
    sortDirection: str = Query("asc"),
) -> WantedPage:
    """Paged derived-missing list over ``repo.wanted_issues()`` (FRG-API-012)."""
    db = request.app.state.db
    async with db.read_session() as session:
        result = await paginate(
            session,
            stmt=wanted_issues(),
            page=page,
            page_size=pageSize,
            sort_key=sortKey,
            sort_direction=sortDirection,
            whitelist=_SORT_WHITELIST,
        )
        rows: list[IssueRow] = result["records"]
        series_by_id = await load_series_map(session, {r.series_id for r in rows})
    result["records"] = [
        _to_resource(row, series_by_id.get(row.series_id)) for row in rows
    ]
    return WantedPage(**result)


__all__ = ["router"]
