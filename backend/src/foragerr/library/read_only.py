"""The read-only reference-library refusal boundary (FRG-SER-021, FRG-SER-022).

One exception type and one guard, shared by every entry point that would write
under a read-only root or acquire into a series that lives on one — the API
routes, the library flows, and the command handlers behind them. Keeping the
policy here (rather than restating it per endpoint) means a new write or
acquire surface fails closed by calling one function, and the API translates
the refusal in exactly one place.

The guards read the boundary through ``repo.series_is_read_only`` /
``repo.read_only_issue_ids``, so the persisted ``root_folders.read_only`` flag
stays the single truth source.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from foragerr.db import Database
from foragerr.library import repo

__all__ = [
    "ReadOnlySeriesError",
    "refuse_read_only_issues",
    "refuse_read_only_series",
    "refuse_read_only_series_in",
]


class ReadOnlySeriesError(RuntimeError):
    """An operation was attempted that would write to, or acquire into, a
    series on a read-only reference root (FRG-SER-021/022).

    Raised fail-closed BEFORE any byte is written, any row is removed, or any
    grab is enqueued, so the operator's real files stay untouched even when a
    caller reaches the operation by an unexpected route (e.g. enqueuing a
    file-mutating command directly). The API maps it to one 409."""


async def refuse_read_only_series(
    session: AsyncSession, series_id: int, *, action: str
) -> None:
    """Refuse ``action`` when ``series_id`` sits on a read-only root.

    ``action`` is the user-facing verb phrase named in the refusal ("deleting
    files", "renaming files", ...), so the caller reads WHY it was refused and
    which series is browse-only."""
    if await repo.series_is_read_only(session, series_id):
        raise ReadOnlySeriesError(
            f"series {series_id} is on a read-only reference library "
            f"(browse and serve only); {action} is not available for it"
        )


async def refuse_read_only_series_in(
    db: Database, series_id: int, *, action: str
) -> None:
    """:func:`refuse_read_only_series` for callers holding only a database —
    the enqueue-only endpoints, which refuse up front so the operator gets a
    4xx instead of a command that fails later in a worker."""
    async with db.read_session() as session:
        await refuse_read_only_series(session, series_id, action=action)


async def refuse_read_only_issues(
    session: AsyncSession, issue_ids: Sequence[int], *, action: str
) -> None:
    """Refuse ``action`` when ANY of ``issue_ids`` belongs to a read-only
    series — all-or-none, matching the bulk toggles' own atomicity: one
    browse-only issue in the batch refuses the whole request rather than
    silently applying to the rest."""
    offending = await repo.read_only_issue_ids(session, issue_ids)
    if offending:
        raise ReadOnlySeriesError(
            f"issue(s) {offending} belong to a read-only reference library "
            f"(browse and serve only); {action} is not available for them"
        )
