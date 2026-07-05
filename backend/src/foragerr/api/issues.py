"""Issue HTTP surface (FRG-API-004, FRG-API-006).

Thin translation layer over the frozen ``foragerr.library.repo`` module. No
business logic lives here. Issue numbers are exposed verbatim as strings
(never coerced to int/float — FRG-SER-002/FRG-DB-008): the resource field
below is typed ``str | None``, matching ``IssueRow.issue_number``'s
``IssueNumberText`` column exactly, so Pydantic never gets a chance to
mis-coerce ``"1.5"``/``"1.MU"``.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from foragerr.api.errors import ApiError
from foragerr.api.paging import paginate
from foragerr.library import repo
from foragerr.library.models import IssueRow

router = APIRouter(prefix="/issues", tags=["issues"])

#: Whitelisted sort keys -> fixed column expressions (FRG-API-006).
#: ``ordering_key`` is the default/primary sort (persisted reading order).
_SORT_WHITELIST = {
    "ordering_key": IssueRow.ordering_key,
    "added_at": IssueRow.added_at,
}


# --- resource models ---------------------------------------------------------


class IssueFileResource(BaseModel):
    id: int
    path: str
    size: int


class IssueResource(BaseModel):
    id: int
    series_id: int
    cv_issue_id: int
    #: Verbatim string — NEVER int/float (FRG-API-004 scenario:
    #: "1.5"/"1.MU" must round-trip unchanged).
    issue_number: str | None
    title: str | None
    cover_date: dt.date | None
    store_date: dt.date | None
    issue_type: str
    monitored: bool
    added_at: dt.datetime
    has_file: bool
    file: IssueFileResource | None

    @classmethod
    def from_row(cls, row: IssueRow) -> "IssueResource":
        # M1 simplification: an issue may in principle have more than one
        # issue_files row; only the lowest-id one is surfaced as the nested
        # `file`. `has_file` still reflects presence of ANY file row.
        first = min(row.files, key=lambda f: f.id) if row.files else None
        return cls(
            id=row.id,
            series_id=row.series_id,
            cv_issue_id=row.cv_issue_id,
            issue_number=row.issue_number,
            title=row.title,
            cover_date=row.cover_date,
            store_date=row.store_date,
            issue_type=row.issue_type,
            monitored=row.monitored,
            added_at=row.added_at,
            has_file=bool(row.files),
            file=(
                IssueFileResource(id=first.id, path=first.path, size=first.size)
                if first is not None
                else None
            ),
        )


class IssuePage(BaseModel):
    """Paging envelope (FRG-API-006) specialized for issue resources."""

    page: int
    pageSize: int
    sortKey: str
    sortDirection: str
    totalRecords: int
    records: list[IssueResource]


class IssueMonitorUpdate(BaseModel):
    """Request body for the single-issue monitored toggle."""

    monitored: bool


class IssueBulkMonitorUpdate(BaseModel):
    """Request body for ``PUT /api/v1/issues/monitor`` (bulk toggle)."""

    issue_ids: list[int]
    monitored: bool


class IssueBulkMonitorResult(BaseModel):
    issue_ids: list[int]
    monitored: bool


# --- routes -------------------------------------------------------------------


@router.get("", response_model=IssuePage)
async def list_issues(
    request: Request,
    seriesId: int = Query(...),
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=200),
    sortKey: str = Query("ordering_key"),
    sortDirection: str = Query("asc"),
) -> IssuePage:
    """Issues of one series, paged, ordered by the persisted ordering key by
    default (FRG-API-004, FRG-API-006)."""
    db = request.app.state.db
    async with db.read_session() as session:
        stmt = (
            select(IssueRow)
            .where(IssueRow.series_id == seriesId)
            .options(selectinload(IssueRow.files))
        )
        result = await paginate(
            session,
            stmt=stmt,
            page=page,
            page_size=pageSize,
            sort_key=sortKey,
            sort_direction=sortDirection,
            whitelist=_SORT_WHITELIST,
        )
    result["records"] = [IssueResource.from_row(row) for row in result["records"]]
    return IssuePage(**result)


# NOTE: registered BEFORE "/{issue_id}" so "monitor" is never swallowed by
# the int-typed path parameter.
@router.put("/monitor", response_model=IssueBulkMonitorResult)
async def bulk_update_monitored(
    body: IssueBulkMonitorUpdate, request: Request
) -> IssueBulkMonitorResult:
    """Bulk monitored toggle, atomic (all-or-none) via one write_session
    (FRG-API-004): a missing id rolls back the WHOLE request — nothing
    changes for any of the named issues."""
    db = request.app.state.db
    try:
        async with db.write_session() as session:
            await repo.bulk_set_issue_monitored(
                session, body.issue_ids, body.monitored
            )
    except LookupError as exc:
        raise ApiError(404, str(exc)) from exc
    return IssueBulkMonitorResult(issue_ids=body.issue_ids, monitored=body.monitored)


@router.put("/{issue_id}", response_model=IssueResource)
async def update_monitored(
    issue_id: int, body: IssueMonitorUpdate, request: Request
) -> IssueResource:
    """Single-issue monitored toggle (FRG-API-004).

    The response is read back INSIDE the same ``write_session`` right after
    the mutation (eager-loading ``files`` before the transaction closes)
    rather than in a second, separate session: ``write_session`` holds the
    single-writer lock for its whole duration (db/engine.py), so no
    concurrent request can delete the row in the gap between the toggle and
    this re-read — one session removes both the extra round trip and the
    race a two-session split would otherwise need to guard against."""
    db = request.app.state.db
    try:
        async with db.write_session() as session:
            await repo.set_issue_monitored(session, issue_id, body.monitored)
            row = (
                await session.execute(
                    select(IssueRow)
                    .where(IssueRow.id == issue_id)
                    .options(selectinload(IssueRow.files))
                )
            ).scalar_one()
    except LookupError as exc:
        raise ApiError(404, str(exc)) from exc
    return IssueResource.from_row(row)
