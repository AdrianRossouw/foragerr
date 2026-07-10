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
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from foragerr.api.errors import ApiError
from foragerr.api.paging import paginate
from foragerr.library import containment, repo
from foragerr.library.containment import (
    ContainmentNotFoundError,
    ContainmentValidationError,
    RangeInput,
)
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


class CollectedInResource(BaseModel):
    """One "collected in" chip on an issue (FRG-API-022): a trade-typed series
    that collects this issue, and the range label it falls under. Lets the
    detail table render chips without an N+1 lookup per issue."""

    trade_series_id: int
    trade_series_title: str
    trade_issue_id: int
    #: The collecting trade's book-type (``tpb``/``gn``/``hc``/``one_shot``);
    #: a trade always has one, but typed nullable for defensiveness.
    booktype: str | None
    range_label: str

    @classmethod
    def from_membership(
        cls, m: "containment.CollectedInMembership"
    ) -> "CollectedInResource":
        return cls(
            trade_series_id=m.trade_series_id,
            trade_series_title=m.trade_series_title,
            trade_issue_id=m.trade_issue_id,
            booktype=m.booktype,
            range_label=m.range_label,
        )


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
    #: Trade-containment memberships (FRG-API-022) — the collecting trades this
    #: issue falls under. Empty list when none (additive; the single-issue
    #: toggle endpoints never populate it).
    collected_in: list[CollectedInResource] = []

    @classmethod
    def from_row(
        cls,
        row: IssueRow,
        collected_in: list["containment.CollectedInMembership"] | None = None,
    ) -> "IssueResource":
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
            collected_in=[
                CollectedInResource.from_membership(m) for m in (collected_in or [])
            ],
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


class CollectionRangeInput(BaseModel):
    """One requested contiguous sub-range in a containment declaration
    (FRG-API-022): a target series and the two endpoint issues (inclusive)
    chosen from that series' issue list."""

    target_series_id: int
    start_issue_id: int
    end_issue_id: int


#: Upper bound on how many sub-ranges one declare/replace may carry. Bounds the
#: per-range existence work done under the global write lock (a real collected
#: edition never legitimately declares anywhere near this many sub-ranges).
MAX_CONTAINMENT_RANGES = 100


class IssueCollectionsUpdate(BaseModel):
    """Request body for ``PUT /api/v1/issues/{id}/collections`` — replace-all
    semantics: the supplied ranges become the trade issue's complete
    containment set. ``[]`` clears it (equivalent to DELETE). The list is capped
    at ``MAX_CONTAINMENT_RANGES`` (a 400 via the uniform validation shape
    otherwise)."""

    ranges: list[CollectionRangeInput] = Field(max_length=MAX_CONTAINMENT_RANGES)


class StoredRangeResource(BaseModel):
    """One stored containment range in the write-back response."""

    target_series_id: int
    range_label: str


class IssueCollectionsResource(BaseModel):
    """The trade issue's containment set after a declare/replace write
    (FRG-API-022)."""

    trade_issue_id: int
    ranges: list[StoredRangeResource]


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
        # One bounded query for the whole page's collected-in chips (no N+1).
        chips = await containment.collected_in_for_series(session, seriesId)
    result["records"] = [
        IssueResource.from_row(row, chips.get(row.id)) for row in result["records"]
    ]
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


@router.put("/{issue_id}/collections", response_model=IssueCollectionsResource)
async def replace_issue_collections(
    issue_id: int, body: IssueCollectionsUpdate, request: Request
) -> IssueCollectionsResource:
    """Declare/replace a trade issue's containment records (FRG-API-022).

    Replace-all: the supplied ranges become the trade issue's complete
    containment set (``ranges: []`` clears it). Validated by the repo layer —
    the issue must belong to a trade-typed series, each target series must
    exist, both endpoint issues must belong to it, and the bounds must be
    ordered — with any failure mapped to the standard 400 error shape naming
    the offending field. Writes touch ONLY containment rows."""
    db = request.app.state.db
    try:
        async with db.write_session() as session:
            rows = await containment.replace_issue_collections(
                session,
                issue_id,
                [
                    RangeInput(
                        target_series_id=r.target_series_id,
                        start_issue_id=r.start_issue_id,
                        end_issue_id=r.end_issue_id,
                    )
                    for r in body.ranges
                ],
            )
            ranges = [
                StoredRangeResource(
                    target_series_id=row.target_series_id, range_label=row.range_label
                )
                for row in rows
            ]
    except ContainmentNotFoundError as exc:
        raise ApiError(404, str(exc)) from exc
    except ContainmentValidationError as exc:
        raise ApiError(400, str(exc), field=exc.field) from exc
    return IssueCollectionsResource(trade_issue_id=issue_id, ranges=ranges)


@router.delete("/{issue_id}/collections", status_code=204)
async def delete_issue_collections(issue_id: int, request: Request) -> Response:
    """Clear a trade issue's containment records (FRG-API-022). Idempotent —
    a trade issue with no records still returns 204. Touches only containment
    rows."""
    db = request.app.state.db
    async with db.write_session() as session:
        await containment.delete_issue_collections(session, issue_id)
    return Response(status_code=204)
