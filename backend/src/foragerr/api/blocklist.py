"""The blocklist HTTP surface (FRG-UI-017): read + remove blocked releases.

``GET /api/v1/blocklist`` pages the multi-field failed-release blocklist
(written by the tracking failure loop and the manual queue-remove — WRITE
behavior is untouched here). ``DELETE /blocklist/{id}`` and the bulk
``POST /blocklist/delete`` remove entries; the search decision engine snapshots
the table per search (``downloads.stores.load_blocklist_store``), so a removed
row makes that release grabbable again on the next evaluation with no cache to
invalidate.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from sqlalchemy import delete, select

from foragerr.api.errors import ApiError
from foragerr.api.paging import load_issue_map, load_series_map, paginate
from foragerr.downloads.models import BlocklistRow
from foragerr.library.models import IssueRow, SeriesRow

router = APIRouter(prefix="/blocklist", tags=["blocklist"])

_SORT_WHITELIST = {
    "created_at": BlocklistRow.created_at,
    "source_title": BlocklistRow.source_title,
}


class BlocklistSeries(BaseModel):
    id: int
    title: str


class BlocklistIssue(BaseModel):
    id: int
    issueNumber: str | None
    title: str | None


class BlocklistResource(BaseModel):
    """One blocked release as the blocklist exposes it (FRG-UI-017)."""

    id: int
    seriesId: int | None
    issueId: int | None
    series: BlocklistSeries | None
    issue: BlocklistIssue | None
    sourceTitle: str | None
    guid: str | None
    indexer: str | None
    protocol: str | None
    downloadId: str | None
    #: The failure explanation, verbatim.
    message: str | None
    date: dt.datetime


class BlocklistPage(BaseModel):
    """Paging envelope (FRG-API-002) specialized for blocklist resources."""

    page: int
    pageSize: int
    sortKey: str
    sortDirection: str
    totalRecords: int
    records: list[BlocklistResource]


class BlocklistBulkDelete(BaseModel):
    """Request body for ``POST /api/v1/blocklist/delete``."""

    ids: list[int]


def _to_resource(
    row: BlocklistRow,
    series: SeriesRow | None,
    issue: IssueRow | None,
) -> BlocklistResource:
    return BlocklistResource(
        id=row.id,
        seriesId=row.series_id,
        issueId=row.issue_id,
        series=BlocklistSeries(id=series.id, title=series.title) if series else None,
        issue=(
            BlocklistIssue(
                id=issue.id, issueNumber=issue.issue_number, title=issue.title
            )
            if issue
            else None
        ),
        sourceTitle=row.source_title,
        guid=row.guid,
        indexer=row.indexer_name,
        protocol=row.protocol,
        downloadId=row.download_id,
        message=row.message,
        date=row.created_at,
    )


@router.get("", response_model=BlocklistPage)
async def list_blocklist(
    request: Request,
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=200),
    sortKey: str = Query("created_at"),
    sortDirection: str = Query("desc"),
) -> BlocklistPage:
    """Paged blocklist, newest first by default (FRG-UI-017)."""
    db = request.app.state.db
    async with db.read_session() as session:
        result = await paginate(
            session,
            stmt=select(BlocklistRow),
            page=page,
            page_size=pageSize,
            sort_key=sortKey,
            sort_direction=sortDirection,
            whitelist=_SORT_WHITELIST,
            # Failure storms write many rows at one `created_at`; the id
            # tiebreak keeps the default newest-first pages from overlapping.
            tiebreak=BlocklistRow.id,
        )
        rows: list[BlocklistRow] = result["records"]
        series_by_id = await load_series_map(session, {r.series_id for r in rows})
        issue_by_id = await load_issue_map(session, {r.issue_id for r in rows})
    result["records"] = [
        _to_resource(
            row, series_by_id.get(row.series_id), issue_by_id.get(row.issue_id)
        )
        for row in rows
    ]
    return BlocklistPage(**result)


@router.delete("/{blocklist_id}", status_code=200)
async def delete_blocklist_item(
    blocklist_id: int, request: Request
) -> dict[str, object]:
    """Remove one blocklist entry (404 unknown) — the release becomes grabbable
    again the next time the search engine snapshots the table (FRG-UI-017)."""
    db = request.app.state.db
    async with db.write_session() as session:
        row = await session.get(BlocklistRow, blocklist_id)
        if row is None:
            raise ApiError(404, f"blocklist entry {blocklist_id} not found")
        await session.delete(row)
    return {"id": blocklist_id, "removed": True}


@router.post("/delete", status_code=200)
async def bulk_delete_blocklist(
    body: BlocklistBulkDelete, request: Request
) -> dict[str, list[int]]:
    """Bulk remove: deletes the entries that exist and REPORTS the ones that
    do not, so a stale UI selection surfaces as partial success, never a 404
    that hides how far the operation got (FRG-UI-017)."""
    db = request.app.state.db
    requested = list(dict.fromkeys(body.ids))  # de-dup, preserve order
    async with db.write_session() as session:
        found = (
            (
                await session.execute(
                    select(BlocklistRow).where(BlocklistRow.id.in_(requested))
                )
            )
            .scalars()
            .all()
        )
        found_ids = {row.id for row in found}
        if found_ids:
            # One set-based DELETE instead of a delete() per row (the ORM would
            # otherwise issue N statements for a large stale selection).
            await session.execute(
                delete(BlocklistRow).where(BlocklistRow.id.in_(found_ids))
            )
    return {
        "deleted": [i for i in requested if i in found_ids],
        "missing": [i for i in requested if i not in found_ids],
    }


__all__ = ["router"]
