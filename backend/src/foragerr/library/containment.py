"""Trade containment: declare/replace/delete writes and display-only reads.

FRG-SER-020 / FRG-API-022. A *containment record* maps one issue of a
trade-typed series (one collected book) to a target series plus a contiguous
issue range, stored as copied ordering-key bounds
(:class:`foragerr.library.models.IssueCollectionRow`). This module owns:

- the write path (:func:`replace_issue_collections`, replace-all semantics
  with full validation; :func:`delete_issue_collections`), and
- the two display-only reads the detail screen needs — per-issue chip
  memberships (:func:`collected_in_for_series`) and the per-collected-book
  rollup with request-time singles-coverage (:func:`collections_for_series`).

Every read here is a bounded query (no N+1) and NOTHING in this module touches
the derived-wanted choke point (``repo.wanted_issues``) or ``series_statistics``
— containment is display-only and never suppresses single-issue wanted state
(extends FRG-SER-019, proven by the compiled-SQL absence test). Like
``foragerr.library.repo``, every function takes an already-open
:class:`~sqlalchemy.ext.asyncio.AsyncSession`; nothing opens its own session.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import case, delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from foragerr.db.base import utcnow
from foragerr.library.models import (
    IssueCollectionRow,
    IssueFileRow,
    IssueRow,
    SeriesRow,
)

#: En dash joining the two endpoints of a multi-issue range label ("#1–#6").
_RANGE_DASH = "–"


class ContainmentNotFoundError(LookupError):
    """The trade issue named by a containment write does not exist (-> HTTP
    404)."""


class ContainmentValidationError(ValueError):
    """A containment write failed validation (-> HTTP 400).

    Carries the offending ``field`` (mirroring the flows' validation errors) so
    the API can surface it in the standard ``{"errors": [{"field", "message"}]}``
    shape. Raised BEFORE any row is written, so a rejected declaration leaves
    the trade issue's existing containment untouched.
    """

    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field


@dataclass(frozen=True, slots=True)
class RangeInput:
    """One requested contiguous sub-range: a target series and the two endpoint
    issues (inclusive) chosen from that series' issue list."""

    target_series_id: int
    start_issue_id: int
    end_issue_id: int


def _range_label(start: IssueRow, end: IssueRow) -> str:
    """Human-readable label from the endpoints' verbatim issue numbers:
    ``"#1–#6"`` for a span, ``"#8"`` for a single-issue range."""
    start_num = start.issue_number if start.issue_number is not None else "?"
    end_num = end.issue_number if end.issue_number is not None else "?"
    if start.id == end.id or start_num == end_num:
        return f"#{start_num}"
    return f"#{start_num}{_RANGE_DASH}#{end_num}"


async def replace_issue_collections(
    session: AsyncSession, trade_issue_id: int, ranges: list[RangeInput]
) -> list[IssueCollectionRow]:
    """Replace ALL containment records of ``trade_issue_id`` with ``ranges``
    (FRG-SER-020 declare/replace).

    Validates, raising BEFORE any write (so a rejected request changes
    nothing):

    - the trade issue exists (:class:`ContainmentNotFoundError`) and belongs to
      a trade-typed series — ``series.booktype IS NOT NULL``
      (:class:`ContainmentValidationError`, ``field="issue_id"``);
    - per range: the target series exists (``field="target_series_id"``), both
      endpoint issues exist AND belong to that target series
      (``field="start_issue_id"``/``"end_issue_id"``), and the start does not
      sort after the end by ordering key (``field="end_issue_id"``).

    On success replaces the trade issue's records wholesale (delete-all then
    insert), deriving each ``range_label`` from the endpoints' verbatim issue
    numbers and writing ``source="declared"``, ``confidence=1.0``. Returns the
    freshly-inserted rows in input order. Touches ONLY containment rows.
    """
    trade_issue = await session.get(IssueRow, trade_issue_id)
    if trade_issue is None:
        raise ContainmentNotFoundError(f"no issue {trade_issue_id}")
    trade_series = await session.get(SeriesRow, trade_issue.series_id)
    if trade_series is None or trade_series.booktype is None:
        raise ContainmentValidationError(
            f"issue {trade_issue_id} is not part of a collected-edition "
            "(trade-typed) series; containment can only be declared on a trade",
            field="issue_id",
        )

    # Validate every range first, collecting the resolved rows to write — no
    # DB mutation happens until all ranges pass.
    resolved: list[tuple[int, str, str, str]] = []
    for rng in ranges:
        target = await session.get(SeriesRow, rng.target_series_id)
        if target is None:
            raise ContainmentValidationError(
                f"target series {rng.target_series_id} does not exist",
                field="target_series_id",
            )
        start = await session.get(IssueRow, rng.start_issue_id)
        if start is None or start.series_id != target.id:
            raise ContainmentValidationError(
                f"start issue {rng.start_issue_id} does not belong to target "
                f"series {rng.target_series_id}",
                field="start_issue_id",
            )
        end = await session.get(IssueRow, rng.end_issue_id)
        if end is None or end.series_id != target.id:
            raise ContainmentValidationError(
                f"end issue {rng.end_issue_id} does not belong to target "
                f"series {rng.target_series_id}",
                field="end_issue_id",
            )
        if start.ordering_key > end.ordering_key:
            raise ContainmentValidationError(
                "range bounds are out of order: the start issue sorts after "
                "the end issue",
                field="end_issue_id",
            )
        resolved.append(
            (target.id, start.ordering_key, end.ordering_key, _range_label(start, end))
        )

    await delete_issue_collections(session, trade_issue_id)
    now = utcnow()
    rows = [
        IssueCollectionRow(
            trade_issue_id=trade_issue_id,
            target_series_id=target_id,
            start_ordering_key=start_key,
            end_ordering_key=end_key,
            range_label=label,
            source="declared",
            confidence=1.0,
            created_at=now,
        )
        for target_id, start_key, end_key, label in resolved
    ]
    session.add_all(rows)
    await session.flush()
    return rows


async def delete_issue_collections(session: AsyncSession, trade_issue_id: int) -> None:
    """Remove every containment record of ``trade_issue_id`` (FRG-SER-020).
    Touches only containment rows; a no-op when there are none."""
    await session.execute(
        delete(IssueCollectionRow).where(
            IssueCollectionRow.trade_issue_id == trade_issue_id
        )
    )


async def list_issue_collections(
    session: AsyncSession, trade_issue_id: int
) -> list[IssueCollectionRow]:
    """Every containment record of one trade issue, in reading order — the
    read-back after a declare/replace write."""
    result = await session.execute(
        select(IssueCollectionRow)
        .where(IssueCollectionRow.trade_issue_id == trade_issue_id)
        .order_by(IssueCollectionRow.start_ordering_key)
    )
    return list(result.scalars().all())


@dataclass(frozen=True, slots=True)
class CollectedInMembership:
    """One chip on a target-series issue: which trade collects it, and under
    what range label."""

    issue_id: int
    trade_series_id: int
    trade_series_title: str
    trade_issue_id: int
    booktype: str | None
    range_label: str


async def collected_in_for_series(
    session: AsyncSession, series_id: int
) -> dict[int, list[CollectedInMembership]]:
    """Per-issue collected-in memberships for ``series_id``'s issues, keyed by
    issue id (FRG-API-022 chips).

    ONE bounded query: every containment record targeting this series, joined
    to its trade issue + trade series for identity, and to the target series'
    issues by ordering-key ``BETWEEN`` the record's bounds — so each issue that
    falls in a declared range gets a membership without an N+1 per issue.
    Issues outside every range simply have no entry (the caller renders no
    chip)."""
    target_issue = aliased(IssueRow)
    trade_issue = aliased(IssueRow)
    trade_series = aliased(SeriesRow)
    ic = IssueCollectionRow

    stmt = (
        select(
            target_issue.id,
            trade_series.id,
            trade_series.title,
            trade_series.booktype,
            trade_issue.id,
            ic.range_label,
        )
        .select_from(ic)
        .join(trade_issue, trade_issue.id == ic.trade_issue_id)
        .join(trade_series, trade_series.id == trade_issue.series_id)
        .join(
            target_issue,
            (target_issue.series_id == ic.target_series_id)
            & (
                target_issue.ordering_key.between(
                    ic.start_ordering_key, ic.end_ordering_key
                )
            ),
        )
        .where(ic.target_series_id == series_id)
        .order_by(target_issue.ordering_key, trade_issue.id)
    )
    result = await session.execute(stmt)

    memberships: dict[int, list[CollectedInMembership]] = {}
    for issue_id, ts_id, ts_title, ts_booktype, ti_id, label in result.all():
        memberships.setdefault(issue_id, []).append(
            CollectedInMembership(
                issue_id=issue_id,
                trade_series_id=ts_id,
                trade_series_title=ts_title,
                trade_issue_id=ti_id,
                booktype=ts_booktype,
                range_label=label,
            )
        )
    return memberships


@dataclass(frozen=True, slots=True)
class CollectionRange:
    """One declared sub-range in a collection rollup entry."""

    target_series_id: int
    label: str
    start_ordering_key: str
    end_ordering_key: str


@dataclass(frozen=True, slots=True)
class CollectionRollup:
    """One collected book that declares at least one range targeting the
    series being viewed (FRG-API-022 collections resource).

    ``coverage`` is computed at REQUEST time over file presence within the
    declared ranges — never a stored column: ``collected`` when every issue in
    every range has a file, ``partial`` when some do, ``none`` when none do (or
    the ranges cover no issues).
    """

    trade_issue_id: int
    trade_series_id: int
    trade_series_title: str
    booktype: str | None
    release_date: dt.date | None
    ranges: list[CollectionRange]
    coverage: str
    issues_in_ranges: int
    owned_in_ranges: int


def _owned_target_issue_expr(target_issue):
    """``target_issue.id`` when it has a file, else NULL — so
    ``count(distinct ...)`` yields the owned (file-backed) count within a range
    without a fan-out join to ``issue_files`` (the display-only rollup pattern,
    mirroring ``repo._owned_issue_id_expr`` but over an aliased issue)."""
    has_file = exists().where(IssueFileRow.issue_id == target_issue.id)
    return case((has_file, target_issue.id), else_=None)


async def collections_for_series(
    session: AsyncSession, series_id: int
) -> list[CollectionRollup]:
    """Per-collected-book rollup for every trade that collects into
    ``series_id`` (FRG-API-022), with request-time singles-coverage.

    Two bounded queries (no N+1): one lists the containment records targeting
    the series (joined to the trade issue/series for identity + release date),
    the other aggregates, per trade issue, how many of the target series'
    issues fall inside its declared ranges and how many of those have a file.
    Coverage is derived from those counts. Pure read — touches no wanted/stats
    state."""
    ic = IssueCollectionRow
    trade_issue = aliased(IssueRow)
    trade_series = aliased(SeriesRow)

    records = (
        await session.execute(
            select(
                ic.trade_issue_id,
                ic.target_series_id,
                ic.range_label,
                ic.start_ordering_key,
                ic.end_ordering_key,
                trade_series.id,
                trade_series.title,
                trade_series.booktype,
                trade_issue.cover_date,
            )
            .select_from(ic)
            .join(trade_issue, trade_issue.id == ic.trade_issue_id)
            .join(trade_series, trade_series.id == trade_issue.series_id)
            .where(ic.target_series_id == series_id)
            .order_by(trade_issue.cover_date, ic.trade_issue_id, ic.start_ordering_key)
        )
    ).all()
    if not records:
        return []

    target_issue = aliased(IssueRow)
    coverage_rows = (
        await session.execute(
            select(
                ic.trade_issue_id,
                func.count(func.distinct(target_issue.id)),
                func.count(func.distinct(_owned_target_issue_expr(target_issue))),
            )
            .select_from(ic)
            .join(
                target_issue,
                (target_issue.series_id == ic.target_series_id)
                & (
                    target_issue.ordering_key.between(
                        ic.start_ordering_key, ic.end_ordering_key
                    )
                ),
            )
            .where(ic.target_series_id == series_id)
            .group_by(ic.trade_issue_id)
        )
    ).all()
    coverage_by_trade = {
        ti_id: (total, owned) for ti_id, total, owned in coverage_rows
    }

    # Preserve the release-ordered record order while grouping by trade issue.
    order: list[int] = []
    grouped: dict[int, dict] = {}
    for (
        ti_id,
        target_series_id,
        label,
        start_key,
        end_key,
        ts_id,
        ts_title,
        ts_booktype,
        cover_date,
    ) in records:
        entry = grouped.get(ti_id)
        if entry is None:
            order.append(ti_id)
            entry = grouped[ti_id] = {
                "trade_series_id": ts_id,
                "trade_series_title": ts_title,
                "booktype": ts_booktype,
                "release_date": cover_date,
                "ranges": [],
            }
        entry["ranges"].append(
            CollectionRange(
                target_series_id=target_series_id,
                label=label,
                start_ordering_key=start_key,
                end_ordering_key=end_key,
            )
        )

    rollups: list[CollectionRollup] = []
    for ti_id in order:
        entry = grouped[ti_id]
        total, owned = coverage_by_trade.get(ti_id, (0, 0))
        if owned == 0:
            coverage = "none"
        elif owned >= total:
            coverage = "collected"
        else:
            coverage = "partial"
        rollups.append(
            CollectionRollup(
                trade_issue_id=ti_id,
                trade_series_id=entry["trade_series_id"],
                trade_series_title=entry["trade_series_title"],
                booktype=entry["booktype"],
                release_date=entry["release_date"],
                ranges=entry["ranges"],
                coverage=coverage,
                issues_in_ranges=total,
                owned_in_ranges=owned,
            )
        )
    return rollups
