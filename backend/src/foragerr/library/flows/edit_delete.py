"""Series edit and delete flows (FRG-SER-014, FRG-SER-008 edit-path scenario).

``edit_series`` mutates only the supplied fields; a path change is validated
under a registered root folder and the on-disk directory is renamed INSIDE the
same write transaction as the row update, so an ``OSError`` from the rename
rolls the row change back (row and disk stay consistent). ``delete_series``
defaults to removing library rows (cascading to issues/issue_files) while
leaving files on disk; ``delete_files=True`` is explicitly unimplemented in M1
and raises before touching anything.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from foragerr.config import Settings
from foragerr.db import Database
from foragerr.library import paths, repo
from foragerr.library.models import RootFolderRow, SeriesRow
from foragerr.library.paths import PathNotUnderRootError, validate_under_root
from foragerr.quality.models import FormatProfileRow

from foragerr.library.flows._common import (
    DeleteFilesNotSupportedError,
    SeriesNotFoundError,
    SeriesValidationError,
    cover_paths,
    validate_monitor_new_items,
)

logger = logging.getLogger("foragerr.library.flows.edit_delete")


async def edit_series(
    db: Database,
    series_id: int,
    *,
    monitored: bool | None = None,
    monitor_new_items: str | None = None,
    format_profile_id: int | None = None,
    root_folder_id: int | None = None,
    path: str | None = None,
) -> SeriesRow:
    """Update only the supplied fields of a series (FRG-SER-014).

    A supplied ``path`` must resolve under a registered root folder
    (:class:`SeriesValidationError` otherwise, row unchanged) and triggers a
    directory rename in the same transaction as the row update.
    """
    if monitor_new_items is not None:
        validate_monitor_new_items(monitor_new_items)

    async with db.write_session() as session:
        series = await repo.get_series(session, series_id)
        if series is None:
            raise SeriesNotFoundError(f"no series {series_id}")

        if format_profile_id is not None:
            await _require_profile(session, format_profile_id)
        if root_folder_id is not None:
            new_root = await _require_root_folder(session, root_folder_id)
            if path is None:
                # No explicit path change: the series' existing path must
                # already resolve under the new root, otherwise root_folder_id
                # and path would silently disagree (no path/directory move
                # ever happens in that case, so the mismatch would be
                # permanent and undetectable via this endpoint).
                try:
                    validate_under_root(series.path, [new_root.path])
                except PathNotUnderRootError as exc:
                    raise SeriesValidationError(
                        f"changing root_folder_id to {root_folder_id} leaves "
                        f"the current path outside it; supply a new path "
                        f"under the new root too: {exc}"
                    ) from exc
            series.root_folder_id = root_folder_id

        if path is not None:
            roots = await repo.list_root_folders(session)
            try:
                validated = validate_under_root(path, [r.path for r in roots])
            except PathNotUnderRootError as exc:
                raise SeriesValidationError(str(exc)) from exc
            new_path = str(validated)
            old_path = series.path
            if new_path != old_path:
                # Checked under the single-writer lock this write_session
                # holds for its whole duration, so no concurrent insert/edit
                # can take this path between the check and the rename below —
                # this closes the rename-then-commit-fails-on-uniqueness
                # ordering hazard, not just a best-effort pre-check.
                taken = await session.scalar(
                    select(SeriesRow.id).where(
                        SeriesRow.path == new_path, SeriesRow.id != series_id
                    )
                )
                if taken is not None:
                    raise SeriesValidationError(
                        f"path {new_path!r} is already used by another series"
                    )
            series.path = new_path
            # Rename INSIDE the transaction: an OSError propagates and rolls
            # back the row change (FRG-SER-008 rollback-on-failure).
            paths.rename_series_directory(old_path, new_path)

        if monitored is not None:
            series.monitored = monitored
        if monitor_new_items is not None:
            series.monitor_new_items = monitor_new_items
        if format_profile_id is not None:
            series.format_profile_id = format_profile_id

    return series


async def delete_series(
    db: Database,
    series_id: int,
    *,
    delete_files: bool = False,
    settings: Settings | None = None,
) -> None:
    """Delete a series (FRG-SER-014).

    ``delete_files=False`` (default) removes the series row — cascading to its
    issue and issue-file rows — while leaving library files on disk untouched.
    ``delete_files=True`` raises :class:`DeleteFilesNotSupportedError` before
    any mutation (the recycle bin is M2, PP-013).

    The series id is baked into the cached-cover filename (``cover_paths()``)
    with no other index back to it, so once the row is gone those files can
    never be found or cleaned up again — they are removed here, best-effort,
    regardless of whether a cover was ever actually cached. ``settings`` is
    optional only for callers that never cache covers (e.g. some tests); the
    API layer always supplies it.
    """
    if delete_files:
        raise DeleteFilesNotSupportedError(
            "deleting files from disk is not supported in M1 (recycle bin is M2)"
        )
    async with db.write_session() as session:
        series = await repo.get_series(session, series_id)
        if series is None:
            raise SeriesNotFoundError(f"no series {series_id}")
        await session.delete(series)

    if settings is not None:
        cover_path, url_path = cover_paths(settings, series_id)
        for stale in (cover_path, url_path):
            try:
                stale.unlink(missing_ok=True)
            except OSError as exc:  # pragma: no cover - best-effort cleanup
                logger.warning(
                    "cover cache cleanup for deleted series %d failed (%s): %s",
                    series_id, stale, exc,
                )


async def _require_profile(session, format_profile_id: int) -> None:
    if await session.get(FormatProfileRow, format_profile_id) is None:
        raise SeriesValidationError(
            f"format profile {format_profile_id} does not exist"
        )


async def _require_root_folder(session, root_folder_id: int) -> RootFolderRow:
    root = await session.get(RootFolderRow, root_folder_id)
    if root is None:
        raise SeriesValidationError(f"root folder {root_folder_id} is not registered")
    return root
