"""Pull-entries repository: per-week idempotent storage (FRG-PULL-003).

Like :mod:`foragerr.library.repo`, every helper here takes an already-open
:class:`~sqlalchemy.ext.asyncio.AsyncSession` — callers open it via
:meth:`foragerr.db.engine.Database.write_session` (writes) or
:meth:`~foragerr.db.engine.Database.read_session` (reads). Nothing in this
module opens its own session, so :func:`replace_week` composes into a larger
write transaction (e.g. the future ``pull-refresh`` command, area D) when a
caller wants fetch+store to share one commit with other work.

Idempotency = per-week replace-on-refresh (FRG-PULL-003): :func:`replace_week`
issues its delete-then-insert against the SAME session/transaction the caller
opened. On the caller's clean exit (``write_session()``'s normal exit path)
the whole replace commits together (FRG-DB-007); on ANY exception raised
inside the caller's ``async with db.write_session()`` block — including one
raised by this function itself, e.g. a unique-constraint violation from a
malformed entry batch — ``write_session()`` rolls the whole transaction back,
so the prior week's stored rows are left untouched. This function never
calls ``commit()`` or ``rollback()`` itself.

Every row this module inserts starts ``match_type="unmatched"`` /
``matched_issue_id=None`` — replace_week is the FETCH/STORE phase only. The
MATCH phase (area C) runs afterward and persists its outcome via
:func:`update_match`.
"""

from __future__ import annotations

import datetime as dt
from typing import Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from foragerr.db.base import utcnow
from foragerr.pull.models import UNMATCHED, ParsedPullEntry, PullEntryRow, entry_key


async def replace_week(
    session: AsyncSession,
    week: str,
    entries: Sequence[ParsedPullEntry],
    *,
    fetched_at: dt.datetime | None = None,
) -> list[PullEntryRow]:
    """Atomically replace week ``week``'s stored entries (FRG-PULL-003).

    Deletes every existing ``pull_entries`` row for ``week`` and inserts one
    row per ``entries``, so a repeated fetch of the same week yields
    identical row counts/content — an entry's ``entry_key`` (not insertion
    order) is what makes it "the same" across refreshes. Rows for OTHER
    weeks are never touched. Returns the newly inserted rows.
    """
    stamp = fetched_at or utcnow()
    await session.execute(delete(PullEntryRow).where(PullEntryRow.week == week))
    # Collapse on entry_key first (FRG-PULL-003): an untrusted source payload may
    # list the same logical row twice — variant covers sharing a cv_issue_id, or a
    # duplicated (series_name, issue_number, publisher) tuple. Without this, two
    # such rows would both be inserted and trip the (week, entry_key) unique
    # constraint at flush, failing the whole pull-refresh run rather than storing
    # the week idempotently. First occurrence wins; order is otherwise irrelevant
    # because entry_key, not insertion order, is what identifies a row.
    deduped: dict[str, ParsedPullEntry] = {}
    for entry in entries:
        deduped.setdefault(entry_key(entry), entry)
    rows = [
        PullEntryRow(
            week=week,
            entry_key=key,
            publisher=entry.publisher,
            series_name=entry.series_name,
            issue_number=entry.issue_number,
            cv_series_id=entry.cv_series_id,
            cv_issue_id=entry.cv_issue_id,
            release_date=entry.release_date,
            matched_issue_id=None,
            match_type=UNMATCHED,
            fetched_at=stamp,
        )
        for key, entry in deduped.items()
    ]
    session.add_all(rows)
    await session.flush()
    return rows


async def list_week(session: AsyncSession, week: str) -> list[PullEntryRow]:
    """All stored entries for ``week``, in insertion (id) order."""
    result = await session.execute(
        select(PullEntryRow).where(PullEntryRow.week == week).order_by(PullEntryRow.id)
    )
    return list(result.scalars().all())


async def any_week_stored(session: AsyncSession) -> bool:
    """Whether the pull store holds ANY entry — the FRG-PULL-010 backfill gate
    (an empty store means fresh install / never fetched)."""
    result = await session.execute(select(PullEntryRow.id).limit(1))
    return result.scalar_one_or_none() is not None


async def get_entry(session: AsyncSession, entry_id: int) -> PullEntryRow | None:
    return await session.get(PullEntryRow, entry_id)


async def update_match(
    session: AsyncSession,
    entry_id: int,
    *,
    matched_issue_id: int | None,
    match_type: str,
) -> None:
    """Persist the matcher's outcome (area C) onto an already-stored entry.

    Writes ONLY the link + ``match_type`` (D4) — never anything
    status-shaped, and never touches the entry's fetched fields.
    """
    row = await session.get(PullEntryRow, entry_id)
    if row is None:
        raise LookupError(f"no pull entry {entry_id}")
    row.matched_issue_id = matched_issue_id
    row.match_type = match_type
