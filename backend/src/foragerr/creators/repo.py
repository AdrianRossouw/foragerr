"""Creators repository helpers (FRG-CRTR-002/004).

Like :mod:`foragerr.library.repo`, every helper takes an already-open
:class:`~sqlalchemy.ext.asyncio.AsyncSession`; nothing here opens its own
session, so calls compose into a larger transaction. The follow-toggle
(:func:`set_creator_followed`) is the storage side of FRG-API-023 / FRG-CRTR-004:
it stamps ``follow_touched`` to mark the flag user-owned. A follow is only ever
explicit — reconciliation writes credits and prunes orphans but never sets
``followed`` — so the user's choice sticks across later refreshes.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from foragerr.creators.models import CreatorRow, IssueCreditRow
from foragerr.db.base import utcnow
from foragerr.library.models import IssueRow


async def get_creator(session: AsyncSession, creator_id: int) -> CreatorRow | None:
    return await session.get(CreatorRow, creator_id)


async def get_creator_by_cv(
    session: AsyncSession, cv_person_id: int
) -> CreatorRow | None:
    return (
        await session.execute(
            select(CreatorRow).where(CreatorRow.cv_person_id == cv_person_id)
        )
    ).scalar_one_or_none()


async def set_creator_followed(
    session: AsyncSession, creator_id: int, followed: bool
) -> CreatorRow:
    """Set a creator's user-owned follow flag and stamp ``follow_touched``.

    Stamping ``follow_touched`` records that the flag is now user-owned. A follow
    is only ever explicit (FRG-CRTR-004, owner decision 2026-07-11): reconciliation
    writes credits and prunes orphans but never sets ``followed``, so a user's
    follow/unfollow sticks across refreshes. ``followed_at`` advances only when
    following; unfollowing leaves the prior timestamp for reference.
    """
    row = await session.get(CreatorRow, creator_id)
    if row is None:
        raise LookupError(f"no creator {creator_id}")
    now = utcnow()
    row.followed = followed
    row.follow_touched = now
    if followed:
        row.followed_at = now
    return row


async def distinct_series_count(session: AsyncSession, creator_id: int) -> int:
    """How many distinct library series this creator has at least one credit in."""
    count = await session.scalar(
        select(func.count(func.distinct(IssueRow.series_id)))
        .select_from(IssueCreditRow)
        .join(IssueRow, IssueRow.id == IssueCreditRow.issue_id)
        .where(IssueCreditRow.creator_id == creator_id)
    )
    return int(count or 0)


async def list_issue_credits(
    session: AsyncSession, issue_id: int
) -> list[IssueCreditRow]:
    """All credit rows for one issue, in id order."""
    result = await session.execute(
        select(IssueCreditRow)
        .where(IssueCreditRow.issue_id == issue_id)
        .order_by(IssueCreditRow.id)
    )
    return list(result.scalars().all())
