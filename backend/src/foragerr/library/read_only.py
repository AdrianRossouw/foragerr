"""The read-only reference-library refusal boundary (FRG-SER-021, FRG-SER-022).

One exception type and one guard, shared by every entry point that would write
under a read-only root or acquire into a series that lives on one — the API
routes, the library flows, the command handlers behind them, and the import
pipeline's placement step. Keeping the policy here (rather than restating it per
endpoint) means a new write or acquire surface fails closed by calling one
function, and the API translates the refusal in exactly one place.

The boundary is derived from TWO independent facts, because either alone can be
made to disagree with the other:

* the series' ``root_folder_id`` pointing at a root whose persisted
  ``root_folders.read_only`` flag is set, and
* the series' (or a candidate file's) resolved PATH lying at or under a
  read-only root's directory, whatever root the row's foreign key names.

Deriving from containment as well as the key is what makes the boundary hold for
a series whose stored path and root key disagree — a state the add/edit
validation refuses to create, but which the boundary must not depend on. Path
resolution is skipped entirely when no read-only root is registered, so an
installation without one pays nothing.

This module imports no session/engine machinery of its own: ``Database`` is a
type-checking-only reference so the boundary stays importable from the importer
package without pulling the db package in.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from foragerr.library import repo
from foragerr.library.models import IssueRow, SeriesRow
from foragerr.security.paths import PathConfinementError, validate_under_root

if TYPE_CHECKING:  # pragma: no cover - typing only
    from foragerr.db import Database

__all__ = [
    "ReadOnlySeriesError",
    "path_is_read_only",
    "refuse_read_only_issues",
    "refuse_read_only_path",
    "refuse_read_only_series",
    "refuse_read_only_series_in",
    "series_is_read_only",
]


class ReadOnlySeriesError(RuntimeError):
    """An operation was attempted that would write to, or acquire into, a
    series on a read-only reference root (FRG-SER-021/022).

    Raised fail-closed BEFORE any byte is written, any row is removed, or any
    grab is enqueued, so the operator's real files stay untouched even when a
    caller reaches the operation by an unexpected route (e.g. enqueuing a
    file-mutating command directly). The API maps it to one 409, so this is the
    ONLY exception type the boundary raises — a second type for the same policy
    would reach a request path unmapped and surface as a 500."""


def _under_any(path: str, roots: Sequence[str]) -> bool:
    """Whether ``path`` resolves at or under one of ``roots``.

    Delegates to the sanctioned containment check (FRG-SEC-004) so symlinked
    spellings of the same directory resolve to the same answer; an empty
    ``roots`` is not contained."""
    if not roots:
        return False
    try:
        validate_under_root(path, list(roots))
    except (PathConfinementError, OSError):
        return False
    return True


async def path_is_read_only(session: AsyncSession, path: str | os.PathLike[str]) -> bool:
    """Whether ``path`` lies at or under a read-only reference root
    (FRG-SER-021).

    The containment half of the boundary: it answers for a path that no row
    describes yet (an import candidate, a proposed series folder, a configured
    disposal directory), so a write can be refused by WHERE it lands rather
    than by which root a row claims."""
    return _under_any(os.fspath(path), await repo.read_only_root_paths(session))


async def series_is_read_only(session: AsyncSession, series_id: int) -> bool:
    """Whether ``series_id`` is a read-only reference series (FRG-SER-021/022).

    True when its root carries the flag OR its stored path lies under a
    read-only root. A series id with no row is NOT read-only: there are no
    files to protect and the caller resolves the absence itself (every flow
    that guards raises its own not-found first, so this never turns a 404 into
    a 409)."""
    if await repo.series_is_read_only(session, series_id):
        return True
    path = await session.scalar(select(SeriesRow.path).where(SeriesRow.id == series_id))
    return path is not None and await path_is_read_only(session, path)


async def refuse_read_only_series(
    session: AsyncSession, series_id: int, *, action: str
) -> None:
    """Refuse ``action`` when ``series_id`` is a read-only reference series.

    ``action`` is the user-facing verb phrase named in the refusal ("deleting
    files", "renaming files", ...), so the caller reads WHY it was refused and
    which series is browse-only."""
    if await series_is_read_only(session, series_id):
        raise ReadOnlySeriesError(
            f"series {series_id} is on a read-only reference library "
            f"(browse and serve only); {action} is not available for it"
        )


async def refuse_read_only_series_in(
    db: "Database", series_id: int, *, action: str
) -> None:
    """:func:`refuse_read_only_series` for callers holding only a database —
    the enqueue-only endpoints, which refuse up front so the operator gets a
    4xx instead of a command that fails later in a worker."""
    async with db.read_session() as session:
        await refuse_read_only_series(session, series_id, action=action)


async def refuse_read_only_path(
    session: AsyncSession, path: str | os.PathLike[str], *, action: str
) -> None:
    """Refuse ``action`` when ``path`` lies under a read-only reference root.

    The path-keyed refusal, for operations named by a location rather than by a
    series: a manual-import source file, a rescan walk override, a configured
    disposal directory. It closes the direction where the target series (or
    destination root) is perfectly writable but the FILES being moved are the
    operator's read-only originals."""
    if await path_is_read_only(session, path):
        raise ReadOnlySeriesError(
            f"{os.fspath(path)} is inside a read-only reference library "
            f"(browse and serve only); {action} is not available for it"
        )


async def refuse_read_only_issues(
    session: AsyncSession, issue_ids: Sequence[int], *, action: str
) -> None:
    """Refuse ``action`` when ANY of ``issue_ids`` belongs to a read-only
    series — all-or-none, matching the bulk toggles' own atomicity: one
    browse-only issue in the batch refuses the whole request rather than
    silently applying to the rest."""
    offending = set(await repo.read_only_issue_ids(session, issue_ids))
    read_only_roots = await repo.read_only_root_paths(session)
    if read_only_roots and issue_ids:
        # Containment half: an issue whose series' files live under a read-only
        # root is browse-only whatever its root key says. One query for the
        # batch, and each distinct series path resolved once.
        rows = (
            await session.execute(
                select(IssueRow.id, SeriesRow.path)
                .join(SeriesRow, SeriesRow.id == IssueRow.series_id)
                .where(IssueRow.id.in_(issue_ids))
            )
        ).all()
        verdicts: dict[str, bool] = {}
        for issue_id, path in rows:
            if issue_id in offending:
                continue
            if path not in verdicts:
                verdicts[path] = _under_any(path, read_only_roots)
            if verdicts[path]:
                offending.add(issue_id)
    if offending:
        raise ReadOnlySeriesError(
            f"issue(s) {sorted(offending)} belong to a read-only reference "
            f"library (browse and serve only); {action} is not available for them"
        )
