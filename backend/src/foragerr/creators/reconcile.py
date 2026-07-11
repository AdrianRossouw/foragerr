"""Per-series credit reconciliation (FRG-CRTR-002/004).

:func:`reconcile_series_credits` runs INSIDE the refresh write transaction,
right after the issue insert/update/delete reconcile (``refresh.py``). For each
fetched issue it upserts the credited creators (CV is authority for names) and
replaces that issue's credit set to match the fetched state — idempotent, so a
repeat refresh writes nothing. It then:

* **prunes** creators that now carry zero credits *and* were never user-touched
  *and* are unfollowed (design decision 4): a followed or user-touched row
  survives even creditless, because pruning it would erase the unfollow memory
  and let a later re-ingest re-seed it followed (which FRG-CRTR-004 forbids);
* **seeds** ``followed`` for creators whose credits now span two or more
  distinct library series, but only while ``follow_touched`` is unset — a user's
  explicit follow/unfollow is never overwritten (FRG-CRTR-004).

Only issues present in the fetch are touched, so a partial fetch
(``Page.complete == False``) never removes credits for absent issues — it
mirrors the issue-deletion skip in the surrounding reconcile. Issues that the
surrounding reconcile deleted cascade their credits at the DB level
(``ON DELETE CASCADE``); the prune step then reaps any creator they orphaned.

This module owns no session lifecycle — the caller's ``write_session()`` commits
or rolls back the whole refresh atomically.
"""

from __future__ import annotations

from typing import Sequence

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from foragerr.creators.models import CreatorRow, IssueCreditRow
from foragerr.db.base import utcnow
from foragerr.library.models import IssueRow
from foragerr.metadata.models import CreditRecord, IssueRecord

#: Distinct-library-series threshold at/above which a never-touched creator is
#: seeded ``followed`` (FRG-CRTR-004: "two or more distinct library series").
FOLLOW_SEED_SERIES_THRESHOLD = 2


async def reconcile_series_credits(
    session: AsyncSession,
    series_id: int,
    records: Sequence[IssueRecord],
) -> None:
    """Reconcile the credits of one series' fetched issues (FRG-CRTR-002/004).

    ``records`` are the mapped issue records from the fetch (``Page.items``);
    only those whose issue row currently exists for ``series_id`` are processed,
    so issues absent from a partial fetch keep their credits untouched.
    """
    result = await session.execute(
        select(IssueRow.id, IssueRow.cv_issue_id).where(
            IssueRow.series_id == series_id
        )
    )
    issue_id_by_cv = {cv_issue_id: issue_id for issue_id, cv_issue_id in result}

    for record in records:
        issue_id = issue_id_by_cv.get(record.cv_issue_id)
        if issue_id is None:  # not persisted (e.g. deleted this reconcile)
            continue
        await _replace_issue_credits(session, issue_id, record.credits)

    await _prune_orphan_creators(session)
    await _seed_threshold_follows(session)


async def _replace_issue_credits(
    session: AsyncSession, issue_id: int, credits: Sequence[CreditRecord]
) -> None:
    """Diff-replace one issue's credit rows to match ``credits`` (idempotent).

    Keyed by ``(creator_id, role_normalized)``: rows the fetch no longer lists
    are deleted, newly listed ones inserted, unchanged ones left alone (so a
    repeat refresh writes nothing).
    """
    desired: dict[tuple[int, str], str] = {}
    for credit in credits:
        creator_id = await _upsert_creator(session, credit.cv_person_id, credit.name)
        desired.setdefault((creator_id, credit.role_normalized), credit.role_verbatim)

    existing = (
        await session.execute(
            select(IssueCreditRow).where(IssueCreditRow.issue_id == issue_id)
        )
    ).scalars().all()
    existing_keys: set[tuple[int, str]] = set()
    for row in existing:
        key = (row.creator_id, row.role_normalized)
        existing_keys.add(key)
        if key not in desired:
            await session.delete(row)

    for (creator_id, role_normalized), role_verbatim in desired.items():
        if (creator_id, role_normalized) in existing_keys:
            continue
        session.add(
            IssueCreditRow(
                issue_id=issue_id,
                creator_id=creator_id,
                role_normalized=role_normalized,
                role_verbatim=role_verbatim,
            )
        )
    await session.flush()


async def _upsert_creator(session: AsyncSession, cv_person_id: int, name: str) -> int:
    """Insert or update a creator by CV person id; CV wins on the name."""
    row = (
        await session.execute(
            select(CreatorRow).where(CreatorRow.cv_person_id == cv_person_id)
        )
    ).scalar_one_or_none()
    if row is None:
        row = CreatorRow(
            cv_person_id=cv_person_id,
            name=name,
            followed=False,
            created_at=utcnow(),
        )
        session.add(row)
        await session.flush()
    elif row.name != name:
        row.name = name  # CV is authority for names (FRG-CRTR-002 Notes)
    return row.id


async def _prune_orphan_creators(session: AsyncSession) -> None:
    """Delete creditless creators that were never user-touched and are unfollowed.

    A followed or user-touched (``follow_touched`` set) creator is spared even
    when creditless — pruning it would erase the unfollow memory (design D4).
    """
    orphans = (
        await session.execute(
            select(CreatorRow).where(
                CreatorRow.followed.is_(False),
                CreatorRow.follow_touched.is_(None),
                ~exists().where(IssueCreditRow.creator_id == CreatorRow.id),
            )
        )
    ).scalars().all()
    for row in orphans:
        await session.delete(row)
    if orphans:
        await session.flush()


async def _seed_threshold_follows(session: AsyncSession) -> None:
    """Seed ``followed`` for never-touched creators crossing the series threshold.

    Counts distinct library series with at least one credit by the creator; at or
    above :data:`FOLLOW_SEED_SERIES_THRESHOLD`, a creator with ``follow_touched``
    unset and ``followed`` false flips on (``follow_touched`` stays NULL — seeding
    is not a user touch). Already-followed or user-touched rows are excluded, so
    re-reconcile never re-seeds and never overwrites a user's choice.
    """
    distinct_series = (
        select(func.count(func.distinct(IssueRow.series_id)))
        .select_from(IssueCreditRow)
        .join(IssueRow, IssueRow.id == IssueCreditRow.issue_id)
        .where(IssueCreditRow.creator_id == CreatorRow.id)
        .correlate(CreatorRow)
        .scalar_subquery()
    )
    to_seed = (
        await session.execute(
            select(CreatorRow).where(
                CreatorRow.follow_touched.is_(None),
                CreatorRow.followed.is_(False),
                distinct_series >= FOLLOW_SEED_SERIES_THRESHOLD,
            )
        )
    ).scalars().all()
    now = utcnow()
    for row in to_seed:
        row.followed = True
        row.followed_at = now  # follow_touched deliberately left NULL
    if to_seed:
        await session.flush()
