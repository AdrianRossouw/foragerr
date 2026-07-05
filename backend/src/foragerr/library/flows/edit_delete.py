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

from foragerr.db import Database
from foragerr.library import paths, repo
from foragerr.library.models import SeriesRow
from foragerr.library.paths import PathNotUnderRootError, validate_under_root

from foragerr.library.flows._common import (
    DeleteFilesNotSupportedError,
    SeriesNotFoundError,
    SeriesValidationError,
    validate_monitor_new_items,
)


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
            await _require_root_folder(session, root_folder_id)
            series.root_folder_id = root_folder_id

        if path is not None:
            roots = await repo.list_root_folders(session)
            try:
                validated = validate_under_root(path, [r.path for r in roots])
            except PathNotUnderRootError as exc:
                raise SeriesValidationError(str(exc)) from exc
            old_path = series.path
            new_path = str(validated)
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
    db: Database, series_id: int, *, delete_files: bool = False
) -> None:
    """Delete a series (FRG-SER-014).

    ``delete_files=False`` (default) removes the series row — cascading to its
    issue and issue-file rows — while leaving files on disk untouched.
    ``delete_files=True`` raises :class:`DeleteFilesNotSupportedError` before
    any mutation (the recycle bin is M2, PP-013)."""
    if delete_files:
        raise DeleteFilesNotSupportedError(
            "deleting files from disk is not supported in M1 (recycle bin is M2)"
        )
    async with db.write_session() as session:
        series = await repo.get_series(session, series_id)
        if series is None:
            raise SeriesNotFoundError(f"no series {series_id}")
        await session.delete(series)


async def _require_profile(session, format_profile_id: int) -> None:
    from foragerr.quality.models import FormatProfileRow

    if await session.get(FormatProfileRow, format_profile_id) is None:
        raise SeriesValidationError(
            f"format profile {format_profile_id} does not exist"
        )


async def _require_root_folder(session, root_folder_id: int) -> None:
    from foragerr.library.models import RootFolderRow

    if await session.get(RootFolderRow, root_folder_id) is None:
        raise SeriesValidationError(f"root folder {root_folder_id} is not registered")
