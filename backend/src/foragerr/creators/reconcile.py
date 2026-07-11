"""Per-series credit reconciliation (FRG-CRTR-002/004).

:func:`reconcile_series_credits` runs INSIDE the refresh write transaction,
right after the issue insert/update/delete reconcile (``refresh.py``). For each
fetched issue it upserts the credited creators (CV is authority for names) and
replaces that issue's credit set to match the fetched state — idempotent, so a
repeat refresh writes nothing. It then:

* **prunes** creators that now carry zero credits *and* were never user-touched
  *and* are unfollowed (design decision 4): a followed or user-touched row
  survives even creditless, because pruning it would erase the unfollow memory
  and let a later re-ingest resurrect it (a followed creator is always a
  user-touched creator, so a spared followed row is spared by the touched
  predicate too).

The system NEVER derives a follow from library contents: ``followed`` only ever
changes through the explicit follow API (FRG-CRTR-004, owner decision
2026-07-11). Reconciliation writes credits and prunes orphans; it does not seed,
default, or otherwise set ``followed``.

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

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from foragerr.creators.models import CreatorRow, IssueCreditRow
from foragerr.db.base import utcnow
from foragerr.library.models import IssueRow
from foragerr.metadata.models import CreditRecord, IssueRecord


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


async def _replace_issue_credits(
    session: AsyncSession, issue_id: int, credits: Sequence[CreditRecord]
) -> None:
    """Diff-replace one issue's credit rows to match ``credits`` (idempotent).

    Keyed by ``(creator_id, role_normalized)``: rows the fetch no longer lists
    are deleted, newly listed ones inserted. A row whose key still matches is
    kept in place, but its ``role_verbatim`` is refreshed when CV's verbatim
    spelling changed (e.g. ``"penciller"`` -> ``"penciler"``, both normalizing
    to ``penciler``) — CV is the authority for that column too (FRG-CRTR-002
    Notes). The verbatim is written only on an actual change, so an identical
    repeat refresh still writes nothing.
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
    existing_by_key: dict[tuple[int, str], IssueCreditRow] = {}
    for row in existing:
        key = (row.creator_id, row.role_normalized)
        if key not in desired:
            await session.delete(row)
        else:
            existing_by_key[key] = row

    for (creator_id, role_normalized), role_verbatim in desired.items():
        existing_row = existing_by_key.get((creator_id, role_normalized))
        if existing_row is not None:
            # Same (creator, normalized role) already stored: keep the row (stable
            # id), but let CV re-author a changed verbatim spelling. Guarded on
            # inequality so idempotency holds (identical input writes nothing).
            if existing_row.role_verbatim != role_verbatim:
                existing_row.role_verbatim = role_verbatim
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
