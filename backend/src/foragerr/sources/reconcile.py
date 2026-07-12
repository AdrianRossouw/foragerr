"""Collected-edition reconciliation (FRG-SRC-007).

A matched collected edition is reconciled against the single-issue run it
collects. This module:

* **computes the fill-set** — the exact issues an edition covers, from the
  trade's declared containment (``issue_collections``, FRG-SER-020) joined to
  the target run by inclusive ordering-key range — partitioned into issues
  already owned as singles vs. fillable ones;
* **marks fillable singles owned-via-edition on import** — one ``issue_files``
  row per fillable single, tagged with the trade ``issues.id`` and ``size = 0``
  (the collected file's bytes count once, on its own file — no double-counting);
* **preserves owned singles** — an issue already backed by its own (non-edition)
  file is never touched, replaced, or double-counted;
* **routes OGN / artbook** (a trade with no declared containment) to the
  standalone path: no fill-set, no single-issue rows fabricated.

**Invariant (FRG-SER-019 extended).** The ONLY wanted-state transition this
produces is *issues becoming owned*, expressed through the existing ownership
channel — the presence of an ``issue_files`` row. It writes NO ``monitored``
flag and adds NO predicate to ``wanted_issues()`` / ``series_statistics`` / the
pull matcher (those still read ownership solely as "an ``issue_files`` row
exists"), so their FRG-SER-019 absence proof is unchanged. ``revert_*`` deletes
the edition rows, returning unfilled singles to wanted.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from foragerr.db.base import utcnow
from foragerr.library.models import IssueCollectionRow, IssueFileRow, IssueRow

#: Ownership state of one covered single in the fill-set.
OWNED_SINGLE = "single"  # already owned by its own file — preserved, untouched
OWNED_EDITION = "edition"  # owned via THIS edition (a size-0 edition file row)
FILLABLE = "fillable"  # released, no file — would be filled on import


@dataclass(frozen=True, slots=True)
class FilledIssue:
    """One covered single issue + its ownership state (UI chip datum)."""

    issue_id: int
    issue_number: str | None
    ownership: str  # OWNED_SINGLE | OWNED_EDITION | FILLABLE


@dataclass(frozen=True, slots=True)
class FillRange:
    """One declared containment range and the issues it covers."""

    target_series_id: int
    range_label: str
    issues: tuple[FilledIssue, ...]


@dataclass(frozen=True, slots=True)
class FillSet:
    """The reconciliation view of a collected edition (FRG-SRC-007)."""

    trade_issue_id: int
    standalone: bool
    ranges: tuple[FillRange, ...] = field(default_factory=tuple)

    @property
    def owned_single_ids(self) -> list[int]:
        return [
            i.issue_id
            for r in self.ranges
            for i in r.issues
            if i.ownership == OWNED_SINGLE
        ]

    @property
    def fillable_ids(self) -> list[int]:
        return [
            i.issue_id
            for r in self.ranges
            for i in r.issues
            if i.ownership == FILLABLE
        ]

    @property
    def edition_owned_ids(self) -> list[int]:
        return [
            i.issue_id
            for r in self.ranges
            for i in r.issues
            if i.ownership == OWNED_EDITION
        ]


async def _owned_single(session: AsyncSession, issue_id: int) -> bool:
    """Whether the issue has its OWN (non-edition) file — owned as a single."""
    row = (
        await session.execute(
            select(IssueFileRow.id).where(
                IssueFileRow.issue_id == issue_id,
                IssueFileRow.edition_issue_id.is_(None),
            )
        )
    ).first()
    return row is not None


async def _edition_owned(
    session: AsyncSession, issue_id: int, trade_issue_id: int
) -> bool:
    """Whether the issue is already filled by THIS edition (idempotency)."""
    row = (
        await session.execute(
            select(IssueFileRow.id).where(
                IssueFileRow.issue_id == issue_id,
                IssueFileRow.edition_issue_id == trade_issue_id,
            )
        )
    ).first()
    return row is not None


async def compute_fill_set(
    session: AsyncSession, *, trade_issue_id: int
) -> FillSet:
    """Compute the fill-set for a collected-edition trade issue (FRG-SRC-007).

    Reads only — the fill-set feeds the entitlement-detail UI chips. A trade
    with no declared containment (OGN / artbook) is ``standalone`` with no
    ranges.
    """
    collections = (
        (
            await session.execute(
                select(IssueCollectionRow)
                .where(IssueCollectionRow.trade_issue_id == trade_issue_id)
                .order_by(IssueCollectionRow.start_ordering_key)
            )
        )
        .scalars()
        .all()
    )
    if not collections:
        return FillSet(trade_issue_id=trade_issue_id, standalone=True)

    ranges: list[FillRange] = []
    for coll in collections:
        issues = (
            (
                await session.execute(
                    select(IssueRow)
                    .where(
                        IssueRow.series_id == coll.target_series_id,
                        IssueRow.ordering_key.between(
                            coll.start_ordering_key, coll.end_ordering_key
                        ),
                    )
                    .order_by(IssueRow.ordering_key)
                )
            )
            .scalars()
            .all()
        )
        filled: list[FilledIssue] = []
        for issue in issues:
            if await _owned_single(session, issue.id):
                ownership = OWNED_SINGLE
            elif await _edition_owned(session, issue.id, trade_issue_id):
                ownership = OWNED_EDITION
            else:
                ownership = FILLABLE
            filled.append(
                FilledIssue(
                    issue_id=issue.id,
                    issue_number=issue.issue_number,
                    ownership=ownership,
                )
            )
        ranges.append(
            FillRange(
                target_series_id=coll.target_series_id,
                range_label=coll.range_label,
                issues=tuple(filled),
            )
        )
    return FillSet(
        trade_issue_id=trade_issue_id, standalone=False, ranges=tuple(ranges)
    )


async def fill_sets_for_series(
    session: AsyncSession, *, series_id: int
) -> list[FillSet]:
    """Every collected-edition fill-set among a series' trade issues.

    The entitlement-detail surface (FRG-SRC-004/007) uses this to render issue
    chips: for a series matched to a collected-edition entitlement, each trade
    issue that declares containment contributes one fill-set. Empty when the
    series collects nothing (an ordinary run, or an OGN with no containment).
    """
    trade_ids = (
        (
            await session.execute(
                select(IssueCollectionRow.trade_issue_id)
                .join(IssueRow, IssueRow.id == IssueCollectionRow.trade_issue_id)
                .where(IssueRow.series_id == series_id)
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    return [
        await compute_fill_set(session, trade_issue_id=tid)
        for tid in sorted(trade_ids)
    ]


async def apply_owned_via_edition(
    session: AsyncSession,
    *,
    trade_issue_id: int,
    edition_file_path: str,
    now: dt.datetime | None = None,
) -> int:
    """Fill covered singles owned-via-edition; return the count newly filled.

    Writes a ``size = 0`` ``issue_files`` row (tagged ``edition_issue_id =
    trade_issue_id``, pointing at the collected file) for each fillable single —
    skipping any already owned as a single (never replaced/double-counted) and
    any already filled by this edition (idempotent). OGN/artbook (no
    containment) writes nothing. Never sets a monitored flag or any
    wanted-suppression predicate — ownership is the ``issue_files`` row alone.
    """
    now = now or utcnow()
    fill_set = await compute_fill_set(session, trade_issue_id=trade_issue_id)
    if fill_set.standalone:
        return 0
    filled = 0
    for issue_id in fill_set.fillable_ids:
        session.add(
            IssueFileRow(
                issue_id=issue_id,
                path=edition_file_path,
                size=0,
                edition_issue_id=trade_issue_id,
                added_at=now,
            )
        )
        filled += 1
    if filled:
        await session.flush()
    return filled


async def revert_owned_via_edition(
    session: AsyncSession, *, trade_issue_id: int
) -> int:
    """Delete every owned-via-edition row this trade provided; return the count.

    Returns the previously-filled singles to wanted (they regain no file of
    their own). Used when a collected-edition entitlement is un-matched/removed.
    """
    rows = (
        (
            await session.execute(
                select(IssueFileRow).where(
                    IssueFileRow.edition_issue_id == trade_issue_id
                )
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        await session.delete(row)
    return len(rows)


async def revert_owned_via_edition_for_series(
    session: AsyncSession, *, series_id: int
) -> int:
    """Delete every owned-via-edition row whose providing trade issue lives in
    ``series_id``; return the count. Real single files (``edition_issue_id IS
    NULL``) are never touched.

    The un-match / ignore cleanup path (FRG-SRC-004/007): a collected-edition
    entitlement is matched to a trade *series*, and its import fills singles
    tagged with that series' trade issue(s). Un-matching or ignoring the imported
    entitlement should return those filled singles to wanted without disturbing
    any real single files the operator owns.
    """
    trade_ids = (
        (
            await session.execute(
                select(IssueRow.id).where(IssueRow.series_id == series_id)
            )
        )
        .scalars()
        .all()
    )
    if not trade_ids:
        return 0
    rows = (
        (
            await session.execute(
                select(IssueFileRow).where(
                    IssueFileRow.edition_issue_id.in_(trade_ids)
                )
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        await session.delete(row)
    return len(rows)


__all__ = [
    "FILLABLE",
    "OWNED_EDITION",
    "OWNED_SINGLE",
    "FillRange",
    "FillSet",
    "FilledIssue",
    "apply_owned_via_edition",
    "compute_fill_set",
    "fill_sets_for_series",
    "revert_owned_via_edition",
    "revert_owned_via_edition_for_series",
]
