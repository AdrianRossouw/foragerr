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

import datetime as dt
import logging
import os

from sqlalchemy import select

from foragerr.config import Settings
from foragerr.db import Database, utcnow
from foragerr.importer import fileops, history
from foragerr.library import paths, repo
from foragerr.library.models import IssueFileRow, IssueRow, RootFolderRow, SeriesRow
from foragerr.library.paths import PathNotUnderRootError, validate_under_root
from foragerr.quality.models import FormatProfileRow

from foragerr.library.flows._common import (
    DeleteFilesNotSupportedError,
    SeriesNotFoundError,
    SeriesValidationError,
    cover_paths,
    encode_aliases,
    validate_aliases,
    validate_monitor_new_items,
)

logger = logging.getLogger("foragerr.library.flows.edit_delete")


class IssueFileNotFoundError(LookupError):
    """No ``issue_files`` row exists for the requested id (FRG-PP-013)."""


async def edit_series(
    db: Database,
    series_id: int,
    *,
    monitored: bool | None = None,
    monitor_new_items: str | None = None,
    format_profile_id: int | None = None,
    root_folder_id: int | None = None,
    path: str | None = None,
    aliases: list[str] | None = None,
) -> SeriesRow:
    """Update only the supplied fields of a series (FRG-SER-014).

    A supplied ``path`` must resolve under a registered root folder
    (:class:`SeriesValidationError` otherwise, row unchanged) and triggers a
    directory rename in the same transaction as the row update. ``aliases``
    (when supplied) REPLACES the stored alternate search names wholesale — the
    user-editable alias list the search engine maps releases through
    (FRG-SRCH-003); pass ``[]`` to clear them.
    """
    if monitor_new_items is not None:
        validate_monitor_new_items(monitor_new_items)
    if aliases is not None:
        validate_aliases(aliases)

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
        if aliases is not None:
            series.aliases = encode_aliases(aliases)

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


async def delete_issue_file(
    db: Database,
    settings: Settings | None,
    issue_file_id: int,
    *,
    now: dt.datetime | None = None,
    offload=None,
) -> str | None:
    """Delete one library file through the app, routing it via the recycle bin
    (FRG-PP-013).

    Ordered so a commit failure can never leave a live ``issue_files`` row
    pointing at a destroyed file (the permanent-delete case would be data loss):

    - **Recycle bin configured** — the file is FIRST moved to the bin (a
      *reversible* move), then the row removal + ``EVENT_FILE_DELETED`` commit; if
      that transaction fails the move is COMPENSATED (the file is moved back to
      its original path) so the row keeps pointing at a real file.
    - **No bin (permanent delete)** — the row removal + event are COMMITTED first,
      and only then is the file unlinked. A post-commit unlink failure leaves an
      orphaned file on disk (recoverable) rather than a dangling row.

    Removing the row alone returns the issue to the derived Wanted state
    (FRG-SER-004). The filesystem work runs off the event loop through ``offload``
    when wired. Returns the recycle destination path, or ``None`` when the file
    was permanently deleted / absent.
    """
    now = now or utcnow()
    # Read the row's identifying data in a read session; the write transaction
    # below re-resolves the row by id so nothing is held across the FS move.
    async with db.read_session() as session:
        row = await session.get(IssueFileRow, issue_file_id)
        if row is None:
            raise IssueFileNotFoundError(f"no issue_files row {issue_file_id}")
        path = row.path
        issue_id = row.issue_id
        issue = await session.get(IssueRow, issue_id)
        series_id = issue.series_id if issue is not None else None

    file_present = os.path.exists(path)
    use_bin = bool(settings is not None and settings.recycle_bin_path and file_present)

    if use_bin:
        # 1. Reversible move to the bin FIRST, then remove the row in a
        #    transaction; on failure, move the file back (compensation).
        dest = await _offloaded(
            offload, fileops.recycle_file, path, settings.recycle_bin_path, now=now
        )
        recycle_path = str(dest)
        try:
            await _commit_file_deletion(
                db, issue_file_id, series_id, issue_id, path, recycle_path, now
            )
        except BaseException:
            try:
                await _offloaded(
                    offload,
                    fileops.place_file,
                    recycle_path,
                    path,
                    mode=fileops.TransferMode.MOVE,
                )
            except Exception:  # pragma: no cover - compensation best-effort
                logger.error(
                    "delete_issue_file: row removal failed AND could not restore "
                    "%s from the recycle bin (%s); file preserved in the bin",
                    path, recycle_path,
                )
            raise
        return recycle_path

    # Permanent-delete (or file already absent): commit the row removal + event
    # FIRST, then unlink after the commit so a crash never orphans the row.
    await _commit_file_deletion(db, issue_file_id, series_id, issue_id, path, None, now)
    if file_present:
        try:
            await _offloaded(offload, os.remove, path)
        except OSError as exc:  # pragma: no cover - orphaned file is recoverable
            logger.warning(
                "delete_issue_file: row removed but unlinking %s failed (%s); "
                "file orphaned on disk (recoverable)", path, exc,
            )
    return None


async def _commit_file_deletion(
    db: Database,
    issue_file_id: int,
    series_id: int | None,
    issue_id: int,
    path: str,
    recycle_path: str | None,
    now: dt.datetime,
) -> None:
    """Remove the issue-file row + write the delete event in one transaction."""
    async with db.write_session() as session:
        await repo.remove_issue_file(session, issue_file_id)
        history.record_event(
            session,
            event_type=history.EVENT_FILE_DELETED,
            series_id=series_id,
            issue_id=issue_id,
            source=history.SOURCE_RESCAN,
            data={"path": path, "recycle_path": recycle_path},
            quarantine_path=recycle_path,
            now=now,
        )


async def _offloaded(offload, func, *args, **kwargs):
    """Run a blocking filesystem op through the offload seam (``None`` = inline)."""
    if offload is not None:
        return await offload(func, *args, **kwargs)
    return func(*args, **kwargs)


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
