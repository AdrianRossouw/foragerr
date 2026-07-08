"""Series edit and delete flows (FRG-SER-014, FRG-SER-008 edit-path scenario,
FRG-API-003 delete-files, FRG-PP-013).

``edit_series`` mutates only the supplied fields; a path change is validated
under a registered root folder and the on-disk directory is renamed INSIDE the
same write transaction as the row update, so an ``OSError`` from the rename
rolls the row change back (row and disk stay consistent). ``delete_series``
defaults to removing library rows (cascading to issues/issue_files) while
leaving files on disk; ``delete_files=True`` (m2-daily-surfaces) routes every
issue file through the same compensated recycle-bin ordering as
``delete_issue_file`` BEFORE any row is removed.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
from typing import ClassVar, Literal

from sqlalchemy import select

from foragerr.commands.registry import BaseCommand, register_command, register_handler
from foragerr.commands.service import HandlerContext
from foragerr.config import Settings
from foragerr.db import Database, utcnow
from foragerr.importer import IMPORT_FILE_MUTATION_GROUP, fileops, history
from foragerr.library import paths, repo
from foragerr.library.models import (
    IssueFileRow,
    IssueRow,
    RootFolderRow,
    SeriesGroupRow,
    SeriesRow,
)
from foragerr.library.paths import PathNotUnderRootError, validate_under_root
from foragerr.quality.models import FormatProfileRow

from foragerr.library.flows._common import (
    GroupEdit,
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


@register_command
class DeleteSeriesFilesCommand(BaseCommand):
    """Delete a series AND recycle its files (FRG-API-003 delete-files scenario).

    ``DELETE /api/v1/series/{id}?deleteFiles=true`` enqueues this rather than
    running inline: the per-file recycle moves are blocking syscalls that, on a
    big series over a slow mount, would freeze the event loop for the whole
    request — and sharing ``IMPORT_FILE_MUTATION_GROUP`` (the manual-import /
    rescan / rename / drain group) serializes it against any concurrent import
    so a rescan cannot add a file into the series after the delete snapshotted
    its file list (which would strand an orphan file with no row/history). Runs
    on the ``pp`` pool with the real ``daemon_offload`` seam for the FS work."""

    name: Literal["delete-series-files"] = "delete-series-files"
    workload_class: ClassVar[str] = "pp"
    exclusivity_group: ClassVar[str | None] = IMPORT_FILE_MUTATION_GROUP
    series_id: int


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
    group_op: GroupEdit | None = None,
) -> SeriesRow:
    """Update only the supplied fields of a series (FRG-SER-014).

    A supplied ``path`` must resolve under a registered root folder
    (:class:`SeriesValidationError` otherwise, row unchanged) and triggers a
    directory rename in the same transaction as the row update. ``aliases``
    (when supplied) REPLACES the stored alternate search names wholesale — the
    user-editable alias list the search engine maps releases through
    (FRG-SRCH-003); pass ``[]`` to clear them.

    ``group_op`` (when supplied) applies one franchise-grouping correction
    (FRG-SER-017): reassign/detach (both LOCK the series so a later refresh
    never re-derives over the choice), rename the series' group, or unlock
    (returns it to auto-derivation on the next refresh). An emptied group is
    pruned.
    """
    if monitor_new_items is not None:
        validate_monitor_new_items(monitor_new_items)
    if aliases is not None:
        validate_aliases(aliases)

    async with db.write_session() as session:
        series = await repo.get_series(session, series_id)
        if series is None:
            raise SeriesNotFoundError(f"no series {series_id}")

        # Apply (and thereby validate) the group op FIRST — BEFORE the
        # irreversible on-disk path rename below. A bad op (e.g. reassign to a
        # nonexistent group) must raise while the transaction can still roll
        # back cleanly with nothing moved on disk; ordering it after the rename
        # would move the directory and only then discover the op is invalid,
        # rolling back the row while leaving the directory moved (disk/DB
        # divergence). Grouping touches only group columns, never the path.
        if group_op is not None:
            await _apply_group_edit(session, series, group_op)

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


async def _apply_group_edit(session, series: SeriesRow, op: GroupEdit) -> None:
    """Apply one franchise-grouping correction inside the edit transaction
    (FRG-SER-017). Touches only ``series.series_group_id`` / ``group_locked``
    (and the group's title on rename) — never any issue/file/wanted state."""
    if op.action == "reassign":
        if op.series_group_id is None:
            raise SeriesValidationError("reassign requires a series_group_id")
        target = await session.get(SeriesGroupRow, op.series_group_id)
        if target is None:
            raise SeriesValidationError(
                f"series group {op.series_group_id} does not exist"
            )
        previous = series.series_group_id
        series.series_group_id = op.series_group_id
        series.group_locked = True
        await session.flush()
        if previous is not None and previous != op.series_group_id:
            await repo.prune_group_if_empty(session, previous)
    elif op.action == "detach":
        previous = series.series_group_id
        series.series_group_id = None
        series.group_locked = True
        await session.flush()
        if previous is not None:
            await repo.prune_group_if_empty(session, previous)
    elif op.action == "rename":
        if op.title is None or not op.title.strip():
            raise SeriesValidationError("rename requires a non-empty title")
        if series.series_group_id is None:
            raise SeriesValidationError(
                "series is not in a group; nothing to rename"
            )
        group = await session.get(SeriesGroupRow, series.series_group_id)
        if group is not None:
            group.title = op.title.strip()
            group.manual_title = True
    elif op.action == "unlock":
        # Clear the lock only — re-derivation happens on the NEXT refresh
        # (FRG-SER-017), never inline here.
        series.group_locked = False
    else:  # pragma: no cover - vocabulary validated at the API boundary
        raise SeriesValidationError(f"unknown group action {op.action!r}")


async def delete_series(
    db: Database,
    series_id: int,
    *,
    delete_files: bool = False,
    settings: Settings | None = None,
    now: dt.datetime | None = None,
    offload=None,
) -> str:
    """Delete a series (FRG-SER-014, FRG-API-003 delete-files scenario).

    ``delete_files=False`` (default) removes the series row — cascading to its
    issue and issue-file rows — while leaving library files on disk untouched.
    ``delete_files=True`` first routes every issue file through the recycle
    bin with the same ordering guarantees as :func:`delete_issue_file`:

    - **Recycle bin configured** — EVERY present file is moved to the bin
      (reversible) FIRST; only when all moves succeeded are the rows removed
      and the per-file ``EVENT_FILE_DELETED`` events (``source=manual``)
      committed, all in ONE transaction. Any failure — a mid-iteration move
      or the commit itself — COMPENSATES the moves already made (files
      restored to their original paths) and re-raises, so a failure never
      leaves rows deleted while files sit in the bin, and never leaves files
      binned while their rows survive pointing nowhere.
    - **No bin (permanent delete)** — rows + events are COMMITTED first and
      the files unlinked only after, so a crash can orphan a file on disk
      (recoverable) but never destroy bytes whose rows survived. A
      post-commit unlink failure is logged and the file left orphaned.

    The series id is baked into the cached-cover filename (``cover_paths()``)
    with no other index back to it, so once the row is gone those files can
    never be found or cleaned up again — they are removed here, best-effort,
    regardless of whether a cover was ever actually cached. ``settings`` is
    optional only for callers that never cache covers and never delete files
    (e.g. some tests); the API layer always supplies it (``delete_files=True``
    without settings falls back to permanent deletion, like
    :func:`delete_issue_file`).

    Returns a one-line summary (``imported``-style, FRG-API-003 finding 6) the
    ``delete-series-files`` command surfaces as its terminal result: how many
    files were deleted and how many of those were routed to the recycle bin
    (per-file destinations already live in the ``file_deleted`` history events).
    """
    if delete_files:
        total, binned = await _delete_series_and_files(
            db, series_id, settings, now or utcnow(), offload
        )
        summary = f"series {series_id} deleted; files={total} binned={binned}"
    else:
        async with db.write_session() as session:
            series = await repo.get_series(session, series_id)
            if series is None:
                raise SeriesNotFoundError(f"no series {series_id}")
            previous_group_id = series.series_group_id
            await session.delete(series)
            await session.flush()
            if previous_group_id is not None:
                # Deleting the last member of a franchise group must not leave a
                # phantom zero-member group behind (it would otherwise surface
                # in GET /series/groups).
                await repo.prune_group_if_empty(session, previous_group_id)
        summary = f"series {series_id} deleted; files=0 binned=0 (rows only)"

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
    return summary


async def _delete_series_and_files(
    db: Database,
    series_id: int,
    settings: Settings | None,
    now: dt.datetime,
    offload,
) -> tuple[int, int]:
    """The ``delete_files=True`` arm of :func:`delete_series`: same per-file
    recycle routing and ordering discipline as :func:`delete_issue_file`, but
    all files move BEFORE one row-removal transaction, and every move is
    compensated on any failure (see ``delete_series``'s docstring for the
    exact guarantee). Returns ``(total_files, binned)``."""
    async with db.read_session() as session:
        series = await repo.get_series(session, series_id)
        if series is None:
            raise SeriesNotFoundError(f"no series {series_id}")
        result = await session.execute(
            select(IssueFileRow)
            .join(IssueRow, IssueRow.id == IssueFileRow.issue_id)
            .where(IssueRow.series_id == series_id)
            .order_by(IssueFileRow.id)
        )
        files = [(row.id, row.path, row.issue_id) for row in result.scalars().all()]

    issue_by_path = {path: issue_id for _fid, path, issue_id in files}
    use_bin = bool(settings is not None and settings.recycle_bin_path)

    if use_bin:
        # 1. Reversibly move EVERY present file to the bin first...
        recycled: dict[int, str | None] = {}
        moved: list[tuple[str, str]] = []  # (original path, bin path)
        try:
            for file_id, path, _issue_id in files:
                if os.path.exists(path):
                    dest = await _offloaded(
                        offload,
                        fileops.recycle_file,
                        path,
                        settings.recycle_bin_path,
                        now=now,
                    )
                    recycled[file_id] = str(dest)
                    moved.append((path, str(dest)))
                else:
                    recycled[file_id] = None
            # 2. ...then remove the rows + write the events in ONE transaction.
            await _commit_series_deletion(db, series_id, files, recycled, now)
        except BaseException:
            # Compensation: restore every file already moved, newest first. A
            # file that ALSO fails to restore is stranded in the bin — record
            # its location durably (below) so it is recoverable from the DB.
            stranded: list[tuple[int | None, str, str]] = []
            for path, dest in reversed(moved):
                try:
                    await _offloaded(
                        offload,
                        fileops.place_file,
                        dest,
                        path,
                        mode=fileops.TransferMode.MOVE,
                    )
                except Exception:  # pragma: no cover - compensation best-effort
                    logger.error(
                        "delete_series: deletion failed AND could not restore "
                        "%s from the recycle bin (%s); file preserved in the bin",
                        path, dest,
                    )
                    stranded.append((issue_by_path.get(path), path, dest))
            if stranded:
                await _record_stranded_bin_files(db, series_id, stranded, now)
            raise
        return len(files), len(moved)

    # Permanent-delete: commit the row removals + events FIRST, then unlink
    # after the commit so a crash never orphans rows (delete_issue_file's
    # documented ordering).
    recycled = {file_id: None for file_id, _path, _issue_id in files}
    await _commit_series_deletion(db, series_id, files, recycled, now)
    for _file_id, path, _issue_id in files:
        if os.path.exists(path):
            try:
                await _offloaded(offload, os.remove, path)
            except OSError as exc:  # pragma: no cover - orphan is recoverable
                logger.warning(
                    "delete_series: rows removed but unlinking %s failed (%s); "
                    "file orphaned on disk (recoverable)", path, exc,
                )
    return len(files), 0


async def _record_stranded_bin_files(
    db: Database,
    series_id: int,
    stranded: list[tuple[int | None, str, str]],
    now: dt.datetime,
) -> None:
    """Durably record files left in the recycle bin after BOTH the row-removal
    commit and the restore-compensation failed (FRG-API-003 finding 5).

    Without this the bin location survives only in a WARNING log — irrecoverable
    from the DB. Each stranded file gets its own ``file_deleted`` history event
    (``source=manual``) carrying the ``quarantine_path`` and a message marking
    it a compensation leftover, written in its OWN transaction so it lands even
    though the deletion transaction rolled back (the series row still exists).
    A failure to write these is logged and swallowed — it must never mask the
    original error that triggered compensation."""
    try:
        async with db.write_session() as session:
            for issue_id, path, dest in stranded:
                history.record_event(
                    session,
                    event_type=history.EVENT_FILE_DELETED,
                    series_id=series_id,
                    issue_id=issue_id,
                    source=history.SOURCE_MANUAL,
                    data={
                        "path": path,
                        "recycle_path": dest,
                        "compensation_leftover": True,
                        "message": (
                            "file left in the recycle bin after a failed "
                            "delete-series compensation; recover it from "
                            "recycle_path"
                        ),
                    },
                    quarantine_path=dest,
                    now=now,
                )
    except Exception:  # pragma: no cover - never mask the original failure
        logger.error(
            "delete_series: could not durably record %d stranded bin file(s) "
            "for series %d; their locations remain only in the warning log",
            len(stranded), series_id,
        )


async def _commit_series_deletion(
    db: Database,
    series_id: int,
    files: list[tuple[int, str, int]],
    recycled: dict[int, str | None],
    now: dt.datetime,
) -> None:
    """Remove the series row (cascading to issues/issue-files) + one
    ``EVENT_FILE_DELETED`` (``source=manual`` — a user action) per file, in
    one transaction."""
    async with db.write_session() as session:
        series = await repo.get_series(session, series_id)
        if series is None:
            # Raced away between the read and this transaction; the caller's
            # compensation restores any files already moved to the bin.
            raise SeriesNotFoundError(f"no series {series_id}")
        previous_group_id = series.series_group_id
        await session.delete(series)
        for file_id, path, issue_id in files:
            recycle_path = recycled.get(file_id)
            history.record_event(
                session,
                event_type=history.EVENT_FILE_DELETED,
                series_id=series_id,
                issue_id=issue_id,
                source=history.SOURCE_MANUAL,
                data={"path": path, "recycle_path": recycle_path},
                quarantine_path=recycle_path,
                now=now,
            )
        if previous_group_id is not None:
            # Deleting the last member of a franchise group must not orphan a
            # phantom zero-member group (mirrors the rows-only delete path).
            await session.flush()
            await repo.prune_group_if_empty(session, previous_group_id)


async def delete_issue_file(
    db: Database,
    settings: Settings | None,
    issue_file_id: int,
    *,
    source: str = history.SOURCE_MANUAL,
    now: dt.datetime | None = None,
    offload=None,
) -> str | None:
    """Delete one library file through the app, routing it via the recycle bin
    (FRG-PP-013).

    ``source`` is the provenance recorded on the ``EVENT_FILE_DELETED`` history
    row; it defaults to ``manual`` because the callers of this flow (the
    ``DELETE /api/v1/issuefile/{id}`` endpoint, FRG-UI-004) act on a user's
    explicit request — this is a user action, not a rescan.

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
                db, issue_file_id, series_id, issue_id, path, recycle_path, source, now
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
    await _commit_file_deletion(
        db, issue_file_id, series_id, issue_id, path, None, source, now
    )
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
    source: str,
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
            source=source,
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


@register_handler("delete-series-files")
async def _handle_delete_series_files(
    command: DeleteSeriesFilesCommand, ctx: HandlerContext
) -> str:
    """Run the file-deleting series delete off the request path, with the real
    ``daemon_offload`` seam so the per-file recycle moves never block the loop."""
    return await delete_series(
        ctx.db,
        command.series_id,
        delete_files=True,
        settings=ctx.settings,
        offload=ctx.offload,
    )
