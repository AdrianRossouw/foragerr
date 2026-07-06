"""Reusable paging-envelope helper for list endpoints (FRG-API-002).

Every paged list endpoint returns the envelope::

    {page, pageSize, sortKey, sortDirection, totalRecords, records[]}

Sort keys are whitelisted per endpoint and mapped to fixed SQLAlchemy column
expressions (``sort_whitelist: {"queued_at": CommandRow.queued_at, ...}``).
The client-supplied ``sortKey``/``sortDirection`` strings are never
interpolated into an ORDER BY clause: an unknown key raises :class:`ApiError`
(400, uniform shape, naming the ``sortKey`` parameter) — not a 500, not a
silent default.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement
from sqlalchemy.sql.selectable import Select

from foragerr.api.errors import ApiError
from foragerr.library.models import IssueRow, SeriesRow

__all__ = [
    "SortWhitelist",
    "envelope",
    "load_issue_map",
    "load_series_map",
    "paginate",
    "resolve_sort_order",
]

#: name -> fixed column expression; never a client-supplied string.
SortWhitelist = Mapping[str, "ColumnElement[Any]"]

_SORT_DIRECTIONS = ("asc", "desc")


def envelope(
    *,
    page: int,
    page_size: int,
    sort_key: str,
    sort_direction: str,
    total_records: int,
    records: Sequence[Any],
) -> dict[str, Any]:
    """Build the shared paging envelope shape."""
    return {
        "page": page,
        "pageSize": page_size,
        "sortKey": sort_key,
        "sortDirection": sort_direction,
        "totalRecords": total_records,
        "records": list(records),
    }


def resolve_sort_order(
    sort_key: str, sort_direction: str, whitelist: SortWhitelist
) -> "ColumnElement[Any]":
    """Map a whitelisted ``sortKey``/``sortDirection`` pair to an ORDER BY term.

    Raises :class:`ApiError` (400) for a key outside the whitelist (naming
    ``sortKey``) or a direction outside ``{asc, desc}`` (naming
    ``sortDirection``). The whitelist is the only source of column
    expressions — the caller-supplied strings are compared against its keys,
    never interpolated into SQL.
    """
    if sort_direction not in _SORT_DIRECTIONS:
        raise ApiError(
            400,
            f"sortDirection must be one of {_SORT_DIRECTIONS} (got {sort_direction!r})",
            field="sortDirection",
        )
    column = whitelist.get(sort_key)
    if column is None:
        raise ApiError(
            400,
            f"unknown sortKey {sort_key!r}; must be one of {sorted(whitelist)}",
            field="sortKey",
        )
    return column.asc() if sort_direction == "asc" else column.desc()


async def paginate(
    session: AsyncSession,
    *,
    stmt: "Select[Any]",
    page: int,
    page_size: int,
    sort_key: str,
    sort_direction: str,
    whitelist: SortWhitelist,
    tiebreak: "ColumnElement[Any] | None" = None,
) -> dict[str, Any]:
    """Run ``stmt`` (a bare, un-ordered/un-limited SELECT over one entity)
    through whitelist-checked sorting, offset/limit paging, and a total
    count, returning the paging envelope with ORM rows in ``records``.

    ``tiebreak`` composes a deterministic SECOND sort term (in the SAME
    direction as the primary sort) after the whitelisted column, so rows that
    tie on the primary sort key — e.g. a whole import batch sharing one
    ``created_at`` — keep a total, stable order across page boundaries.
    Without it, the database is free to return tied rows in any order per
    query, which duplicates or skips rows when the client walks the pages
    (the primary sort alone is not a stable slice). Pass the entity's ``id``
    column (unique) for a guaranteed total order.
    """
    order = resolve_sort_order(sort_key, sort_direction, whitelist)
    order_terms: list[ColumnElement[Any]] = [order]
    if tiebreak is not None:
        order_terms.append(
            tiebreak.asc() if sort_direction == "asc" else tiebreak.desc()
        )
    total = (
        await session.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    rows = (
        await session.execute(
            stmt.order_by(*order_terms).offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()
    return envelope(
        page=page,
        page_size=page_size,
        sort_key=sort_key,
        sort_direction=sort_direction,
        total_records=total,
        records=rows,
    )


async def load_series_map(
    session: AsyncSession, ids: set[int | None]
) -> dict[int, SeriesRow]:
    """Batch-load the series display rows for one page of list resources.

    Shared by every list endpoint that nests a series display object
    (history, wanted, blocklist, queue) so the one-query-per-page batch load
    is never re-implemented per router."""
    real = [i for i in ids if i is not None]
    if not real:
        return {}
    rows = (
        (await session.execute(select(SeriesRow).where(SeriesRow.id.in_(real))))
        .scalars()
        .all()
    )
    return {row.id: row for row in rows}


async def load_issue_map(
    session: AsyncSession, ids: set[int | None]
) -> dict[int, IssueRow]:
    """Batch-load the issue display rows for one page of list resources
    (the issue counterpart of :func:`load_series_map`)."""
    real = [i for i in ids if i is not None]
    if not real:
        return {}
    rows = (
        (await session.execute(select(IssueRow).where(IssueRow.id.in_(real))))
        .scalars()
        .all()
    )
    return {row.id: row for row in rows}
