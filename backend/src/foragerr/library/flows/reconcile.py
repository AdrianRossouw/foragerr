"""Shared DB-vs-disk vanished-file reconciliation (FRG-IMP-022, FRG-SER-010).

Removing ``issue_files`` rows whose backing file has vanished from disk is the
first step of every disk scan: it alone returns the now-fileless monitored
issue to the derived Wanted state (FRG-SER-004), and it clears stale DB records
that would otherwise block re-import of a replacement file. The mechanism
originated in the per-series rescan (:mod:`foragerr.library.flows.rescan`);
m2-existing-library-import generalizes it to root-folder scope for the
library-import scan, so both callers share ONE implementation here and can
never drift.

Split into three composable pieces so each caller keeps its own transaction
shape and offload seam:

- :func:`issue_file_paths_for_series` / :func:`issue_file_paths_for_root` —
  read the candidate ``(issue_file_id, path)`` pairs (read session).
- :func:`vanished_file_ids` — the pure filesystem existence check, a plain
  function so callers can push it through ``offload`` off the event loop.
- :func:`remove_issue_files` — drop the vanished rows (write session).

Root scope is defined by ownership, not path prefix: the rows reconciled for a
root folder are those of series REGISTERED to that root (``series.root_folder_id``),
matching what the root-folder scan is responsible for.
"""

from __future__ import annotations

import os
from typing import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from foragerr.library import repo
from foragerr.library.models import IssueFileRow, IssueRow, SeriesRow

__all__ = [
    "issue_file_paths_for_root",
    "issue_file_paths_for_series",
    "remove_issue_files",
    "vanished_file_ids",
]


async def issue_file_paths_for_series(
    session: AsyncSession, series_id: int
) -> list[tuple[int, str]]:
    """``(issue_file_id, path)`` for every file linked to one series' issues."""
    rows = (
        await session.execute(
            select(IssueFileRow.id, IssueFileRow.path)
            .join(IssueRow, IssueFileRow.issue_id == IssueRow.id)
            .where(IssueRow.series_id == series_id)
        )
    ).all()
    return [(fid, path) for fid, path in rows]


async def issue_file_paths_for_root(
    session: AsyncSession, root_folder_id: int
) -> list[tuple[int, str]]:
    """``(issue_file_id, path)`` for every file of every series registered to
    one root folder (the root-folder scan's reconciliation scope)."""
    rows = (
        await session.execute(
            select(IssueFileRow.id, IssueFileRow.path)
            .join(IssueRow, IssueFileRow.issue_id == IssueRow.id)
            .join(SeriesRow, IssueRow.series_id == SeriesRow.id)
            .where(SeriesRow.root_folder_id == root_folder_id)
        )
    ).all()
    return [(fid, path) for fid, path in rows]


def vanished_file_ids(existing: Sequence[tuple[int, str]]) -> list[int]:
    """The ids of rows whose backing file no longer exists on disk.

    Pure filesystem work (one ``os.path.exists`` per row) — hand it to the
    command context's ``offload`` on big libraries so the existence sweep never
    stalls the shared event loop.
    """
    return [fid for fid, path in existing if not os.path.exists(path)]


async def remove_issue_files(session: AsyncSession, ids: Iterable[int]) -> int:
    """Remove the given ``issue_files`` rows; returns how many were removed."""
    count = 0
    for fid in ids:
        await repo.remove_issue_file(session, fid)
        count += 1
    return count
