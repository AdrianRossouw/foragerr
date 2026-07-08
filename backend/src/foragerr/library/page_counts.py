"""Lazy OPDS-PSE page-count resolution + write-back (FRG-OPDS-009).

The import pipeline caches ``issue_files.page_count`` from the archive report it
already produced, but three kinds of row carry ``NULL``: legacy rows predating
the column, scan-discovered rows, and archives that were unlistable at import.
This service is the first-access fallback the OPDS stream/cover endpoints and the
feed count-read call: it trusts a cached count only when the stored ``size`` still
matches the file on disk (a cheap content-change guard without a hash), otherwise
it re-lists the archive's image members, writes the fresh count back, and returns
it. A ``None`` result means "not listable → no PSE".

It is a pure service over an already-open session and an already-resolved,
confinement-checked path: the caller (OPDS router) does id-only resolution via
``validate_under_root`` and passes ``resolved_path`` — no client path ever reaches
here, and this module never resolves or mutates ``issue_file.path``.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from foragerr.library.models import IssueFileRow
from foragerr.security.archives import (
    DEFAULT_ARCHIVE_LIMITS,
    ArchiveLimits,
    list_image_members,
)


async def resolve_page_count(
    session: AsyncSession,
    issue_file: IssueFileRow,
    resolved_path: Path,
    *,
    limits: ArchiveLimits = DEFAULT_ARCHIVE_LIMITS,
) -> int | None:
    """The cached page count for ``issue_file``, computing + persisting on miss.

    Returns the number of image pages in the archive at ``resolved_path``, or
    ``None`` when the archive is not safely listable (CBR without ``rarfile``,
    corrupt/hostile/oversized container) — i.e. "no PSE".

    Fast path: when ``issue_file.page_count`` is already set AND the stored
    ``issue_file.size`` still equals the file's current on-disk size, the cached
    count is returned WITHOUT opening the archive (the feed-render no-I/O
    guarantee). Otherwise the image members are re-listed via
    :func:`foragerr.security.archives.list_image_members`, the count (or ``None``)
    is written back onto the row along with the refreshed size, and the fresh
    value is returned. ``issue_file.path`` is never touched.
    """
    current_size = resolved_path.stat().st_size
    if issue_file.page_count is not None and issue_file.size == current_size:
        return issue_file.page_count  # trusted cache — no archive open

    members = list_image_members(resolved_path, limits)
    count = len(members) if members is not None else None
    issue_file.page_count = count
    # Refresh the invalidation key so a subsequent access hits the fast path (the
    # row's `path` is deliberately left unchanged — only `size` guards staleness).
    issue_file.size = current_size
    await session.flush()
    return count


__all__ = ["resolve_page_count"]
