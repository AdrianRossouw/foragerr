"""The history HTTP surface: ``GET /api/v1/history`` (FRG-API-011).

A paged read over ``import_history`` — the SINGLE feed source (m2-daily-surfaces
design decision 1): grabs and download failures write their events here beside
their operational tables, so this endpoint never unions ``grab_history`` or the
blocklist. Copies the queue endpoint's pattern (design decision 3): ``paginate``
over the one entity, batch-load the nested series/issue display objects, and a
camelCase Pydantic resource.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from sqlalchemy import select

from foragerr.api.errors import ApiError
from foragerr.api.paging import load_issue_map, load_series_map, paginate
from foragerr.importer.history import IMPORT_EVENT_TYPES, decode_data
from foragerr.importer.models import ImportHistoryRow
from foragerr.library.models import IssueRow, SeriesRow

router = APIRouter(prefix="/history", tags=["history"])

_SORT_WHITELIST = {
    "created_at": ImportHistoryRow.created_at,
    "event_type": ImportHistoryRow.event_type,
}


class HistorySeries(BaseModel):
    id: int
    title: str


class HistoryIssue(BaseModel):
    id: int
    issueNumber: str | None
    title: str | None


class HistoryResource(BaseModel):
    """One pipeline event as the history feed exposes it (FRG-API-011)."""

    id: int
    eventType: str
    sourceTitle: str | None
    downloadId: str | None
    date: dt.datetime
    #: The per-event payload (reasons, provenance, sizes …), decoded verbatim.
    data: dict[str, Any]
    series: HistorySeries | None
    issue: HistoryIssue | None


class HistoryPage(BaseModel):
    """Paging envelope (FRG-API-002) specialized for history resources."""

    page: int
    pageSize: int
    sortKey: str
    sortDirection: str
    totalRecords: int
    records: list[HistoryResource]


def _to_resource(
    row: ImportHistoryRow,
    series: SeriesRow | None,
    issue: IssueRow | None,
) -> HistoryResource:
    return HistoryResource(
        id=row.id,
        eventType=row.event_type,
        sourceTitle=row.source_title,
        downloadId=row.download_id,
        date=row.created_at,
        data=decode_data(row.data),
        series=HistorySeries(id=series.id, title=series.title) if series else None,
        issue=(
            HistoryIssue(
                id=issue.id, issueNumber=issue.issue_number, title=issue.title
            )
            if issue
            else None
        ),
    )


@router.get("", response_model=HistoryPage)
async def list_history(
    request: Request,
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=200),
    sortKey: str = Query("created_at"),
    sortDirection: str = Query("desc"),
    eventType: str | None = Query(None),
    seriesId: int | None = Query(None),
) -> HistoryPage:
    """Paged pipeline-event feed over ``import_history`` only (FRG-API-011).

    ``eventType`` is validated against the writer's own vocabulary — a value no
    writer can produce is a client error (400 naming the field), never a silent
    empty page."""
    if eventType is not None and eventType not in IMPORT_EVENT_TYPES:
        raise ApiError(
            400,
            f"unknown eventType {eventType!r}; "
            f"must be one of {sorted(IMPORT_EVENT_TYPES)}",
            field="eventType",
        )
    stmt = select(ImportHistoryRow)
    if eventType is not None:
        stmt = stmt.where(ImportHistoryRow.event_type == eventType)
    if seriesId is not None:
        stmt = stmt.where(ImportHistoryRow.series_id == seriesId)

    db = request.app.state.db
    async with db.read_session() as session:
        result = await paginate(
            session,
            stmt=stmt,
            page=page,
            page_size=pageSize,
            sort_key=sortKey,
            sort_direction=sortDirection,
            whitelist=_SORT_WHITELIST,
            # Deterministic id tiebreak: a whole import batch shares one
            # ctx.now `created_at`, so without it those tied rows could
            # duplicate/skip across page boundaries (the created_at-then-id
            # order guarantee this feed documents).
            tiebreak=ImportHistoryRow.id,
        )
        rows: list[ImportHistoryRow] = result["records"]
        series_by_id = await load_series_map(session, {r.series_id for r in rows})
        issue_by_id = await load_issue_map(session, {r.issue_id for r in rows})
    result["records"] = [
        _to_resource(
            row, series_by_id.get(row.series_id), issue_by_id.get(row.issue_id)
        )
        for row in rows
    ]
    return HistoryPage(**result)


__all__ = ["router", "load_issue_map", "load_series_map"]
