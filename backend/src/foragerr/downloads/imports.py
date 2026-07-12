"""Completed-download import drain + post-import client cleanup (FRG-DL-009/010).

This is the *flows* half of change 6: it drives change-5's tracked downloads
through the (frozen) change-6 import pipeline and owns the tracked-download state
transitions the pipeline itself deliberately does not touch.

``ProcessImportsCommand`` runs on the ``pp`` (post-processing) worker pool on a
~1-minute cadence, concurrently with change-5's ``TrackDownloadsCommand`` on the
``download`` pool. It drains items sitting in ``import_pending`` (and recovers a
stale ``importing`` row left by a crashed run):

    import_pending → importing → imported                     (all files imported)
                              → import_blocked (with reasons)  (some/all rejected)
                              → failed_pending                 (corrupt archive)

The claim is *status-guarded* (design decision 9): the transition to ``importing``
is an ``UPDATE ... WHERE state IN (import_pending, importing)`` whose ``rowcount``
must be 1. Because every write goes through the single ``write_session()`` writer
lock (FRG-DB-006) and SQLite's ``BEGIN IMMEDIATE``, no other writer can interleave
between the guard's read and its write — so a row TrackDownloadsCommand has just
moved to ``failed_pending`` (or that another worker claimed) fails the guard and
is skipped, never double-processed and never regressed back into a
``CHANGE5_DRIVEN_STATES`` value. Once a row is ``importing`` it sits in change-5's
``_TERMINAL_STATES`` set, so TrackDownloadsCommand will not advance it while the
pipeline runs.

Blocked/failed downloads are never lost and never auto-deleted (FRG-DL-009): the
source file stays in place, the reasons persist on the tracked row and as an
``import_history`` event, and the item is re-drained on a later run once
TrackDownloadsCommand re-reports the client's still-completed item as
``import_pending`` (the retry-on-evidence-change path).

Post-import client cleanup (FRG-DL-010) runs only after a row reaches ``imported``
and only when the owning client's ``remove_completed_downloads`` flag is set —
otherwise the item is merely ``mark_imported``-ed so it is not reprocessed. It
runs *after* the import transaction commits, so client data is never removed
before the ``issue_files`` row is durable.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
from typing import ClassVar, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from foragerr.commands.registry import BaseCommand, register_command, register_handler
from foragerr.commands.service import HandlerContext
from foragerr.config import Settings
from foragerr.db import Database, queue_event, utcnow
from foragerr.downloads.models import DownloadClientRow, TrackedDownloadRow
from foragerr.downloads.repo import load_mappings
from foragerr.downloads.state import (
    TRACKED_STATUS_ERROR,
    TRACKED_STATUS_OK,
    TRACKED_STATUS_WARNING,
    TrackedDownloadState,
)
from foragerr.downloads.tracking import (
    TrackedStateChanged,
    _encode_messages,
    build_client_for_id,
    process_failures,
)
from foragerr.importer import (
    IMPORT_FILE_MUTATION_GROUP,
    CompletedDownloadSource,
    ImportContext,
    ImportOutcome,
    ImportStatus,
    gather,
    history,
    import_candidate,
    media_management_fields,
)
from foragerr.library import repo
from foragerr.library.models import IssueFileRow, IssueRow, SeriesRow
from foragerr.sources.import_hook import apply_source_import

logger = logging.getLogger("foragerr.downloads.imports")

#: ~1-minute cadence, mirroring TrackDownloadsCommand; a module constant (like
#: the ddl area) so no config-schema change is needed for M1.
PROCESS_IMPORTS_INTERVAL = 60
PROCESS_IMPORTS_MIN_INTERVAL = 60
PROCESS_IMPORTS_TASK = "process-imports"

#: States ProcessImportsCommand may claim into ``importing``: a freshly completed
#: download, or a stale ``importing`` row a crashed run left behind (safe to redo
#: — the pipeline's already-imported spec guards a committed import). It never
#: claims ``import_blocked`` — TrackDownloadsCommand re-feeds a still-completed
#: blocked item back to ``import_pending``, which is the retry-on-evidence path.
_CLAIMABLE = (
    TrackedDownloadState.IMPORT_PENDING.value,
    TrackedDownloadState.IMPORTING.value,
)


async def build_import_context(
    db: Database,
    settings: Settings | None,
    *,
    now: dt.datetime,
    offload=None,
) -> ImportContext:
    """Assemble the per-run :class:`ImportContext` for the completed-download drain.

    ``library_root`` is only a free-space-probe fallback here (execution targets
    the resolved series' own folder), so the first configured root folder — or
    the config dir when none exists yet — is a safe default. ``reference_year``
    feeds the evidence parser; the run's wall-clock year is the right anchor for a
    freshly downloaded release.
    """
    config_dir = str(settings.config_dir) if settings is not None else "."
    async with db.read_session() as session:
        roots = await repo.list_root_folders(session)
    library_root = roots[0].path if roots else config_dir
    return ImportContext(
        library_root=library_root,
        config_dir=config_dir,
        reference_year=now.year,
        now=now,
        offload=offload,
        **media_management_fields(settings),
    )


@register_command
class ProcessImportsCommand(BaseCommand):
    """Drain completed downloads through the shared import pipeline (FRG-DL-009).

    On the ``pp`` pool (size 1, serialized with the DDL-queue drain), scheduled
    ~every minute. Serialized within its own exclusivity group so two drains never
    overlap — which lets the claim safely also recover a stale ``importing`` row.
    """

    name: Literal["process-imports"] = "process-imports"
    workload_class: ClassVar[str] = "pp"
    #: Shared with RescanSeriesCommand so a drain and a rescan never mutate the
    #: library concurrently (FRG-SER-010); also serializes the drain against
    #: itself so a stale ``importing`` row can be safely recovered.
    exclusivity_group: ClassVar[str | None] = IMPORT_FILE_MUTATION_GROUP


@register_handler("process-imports")
async def _handle_process_imports(
    command: ProcessImportsCommand, ctx: HandlerContext
) -> str:
    return await process_imports(
        ctx.db, ctx.settings, commands=ctx.commands, offload=ctx.offload
    )


async def process_imports(
    db: Database,
    settings: Settings | None,
    *,
    commands=None,
    offload=None,
    now: dt.datetime | None = None,
) -> str:
    """Drain every claimable completed download through the pipeline (FRG-DL-009).

    Returns an ``"imported=N blocked=M failed=K"`` summary (the command's
    job-history result). Each download is processed independently: a failure in
    one never rolls back another's committed import. ``offload`` (the handler
    passes ``ctx.offload``) routes the pipeline's FS-heavy work off the loop.
    """
    now = now or utcnow()
    ctx = await build_import_context(db, settings, now=now, offload=offload)

    # Snapshot the claimable rows up front (read-only); the per-row guarded claim
    # re-checks state, so a row that changes between snapshot and claim is skipped.
    async with db.read_session() as session:
        row_ids = (
            (
                await session.execute(
                    select(TrackedDownloadRow.id).where(
                        TrackedDownloadRow.state.in_(_CLAIMABLE)
                    )
                )
            )
            .scalars()
            .all()
        )

    imported = blocked = failed = errored = 0
    for row_id in row_ids:
        # One row's unexpected failure (each _process_one owns its own
        # write_session, so nothing leaks across iterations) must not abandon the
        # rest of the batch — it is left in its prior state and retried next cycle.
        try:
            state = await _process_one(
                db, settings, ctx, row_id=row_id, commands=commands
            )
        except Exception:
            errored += 1
            logger.exception("process-imports: row %s failed; retrying next cycle", row_id)
            continue
        if state is TrackedDownloadState.IMPORTED:
            imported += 1
        elif state is TrackedDownloadState.IMPORT_BLOCKED:
            blocked += 1
        elif state is TrackedDownloadState.FAILED_PENDING:
            failed += 1

    summary = f"imported={imported} blocked={blocked} failed={failed}"
    if errored:
        logger.warning("process-imports: %s errored=%d (retry next cycle)", summary, errored)
    else:
        logger.info("process-imports: %s", summary)
    return summary


async def _process_one(
    db: Database,
    settings: Settings | None,
    ctx: ImportContext,
    *,
    row_id: int,
    commands,
) -> TrackedDownloadState | None:
    """Claim, drain, finalize, and clean up one completed download.

    Returns the terminal tracked state applied, or ``None`` when the row could not
    be claimed (raced / vanished / no output path).
    """
    # 1. Status-guarded claim: import_pending|importing -> importing, atomically.
    #    Capture the PRIOR state under the same write lock so we can tell a fresh
    #    completed download from a stale ``importing`` row a crashed run left —
    #    the two need different reconciliation (FRG-DL-009).
    async with db.write_session() as session:
        row = await session.get(TrackedDownloadRow, row_id)
        if row is None or row.state not in _CLAIMABLE:
            return None  # raced with TrackDownloads / already claimed / removed
        was_recovering = row.state == TrackedDownloadState.IMPORTING.value
        row.state = TrackedDownloadState.IMPORTING.value
        row.updated_at = ctx.now
        download_id = row.download_id
        client_id = row.client_id
        client_title = row.title
        output_path = row.output_path
        series_id = row.series_id
        issue_id = row.issue_id

    if not output_path:
        # Claimed but nothing to import from: block, never lose it.
        final_state, status, messages = _resolve_final([], [], no_output=True)
        async with db.write_session() as session:
            await _apply_state(session, row_id, final_state, status, messages, ctx.now)
            await apply_source_import(
                session,
                download_id=download_id,
                final_state=final_state,
                imported_issues=[],
                now=ctx.now,
            )
        return final_state

    # 2. Build the source (mappings passed as data — FRG-PP-008) and gather
    #    candidates in a read session (the filesystem walk holds no write lock).
    mappings = await load_mappings(db, client_id) if client_id is not None else []
    source = CompletedDownloadSource(
        download_id=download_id,
        output_path=output_path,
        client_id=client_id,
        client_title=client_title,
        mappings=tuple(mappings),
    )
    async with db.read_session() as session:
        candidates = await gather(source, session, ctx)

    # 2b. Crash-recovery reconciliation (FRG-DL-009). A crashed prior run may have
    #     already MOVED the file into the library before its DB txn committed —
    #     so the source path is now empty even though the import effectively
    #     happened. Downgrading that to import_blocked would orphan the moved
    #     file and revert the issue to Wanted. Reconcile against the filesystem
    #     first; only fall through to normal handling when nothing is recoverable.
    if was_recovering and not candidates:
        recovered = await _reconcile_recovered_import(
            db,
            ctx,
            row_id=row_id,
            download_id=download_id,
            series_id=series_id,
            issue_id=issue_id,
        )
        if recovered is not None:
            return recovered

    # 3. Import every candidate in ONE write session so each issue_files row and
    #    its history event land atomically with the final state transition.
    outcomes: list[ImportOutcome] = []
    async with db.write_session() as session:
        for candidate in candidates:
            outcomes.append(await import_candidate(session, candidate, ctx))
        final_state, status, messages = _resolve_final(
            candidates, outcomes, no_output=False
        )
        await _apply_state(session, row_id, final_state, status, messages, ctx.now)
        # Store-source hook (FRG-SRC-006/007): mirror the verdict onto the
        # entitlement and, on success, fill owned-via-edition singles for any
        # imported collected edition — all inside this import transaction.
        imported_issues = [
            (o.issue_id, o.imported_path)
            for o in outcomes
            if o.status is ImportStatus.IMPORTED
            and o.issue_id is not None
            and o.imported_path
        ]
        await apply_source_import(
            session,
            download_id=download_id,
            final_state=final_state,
            imported_issues=imported_issues,
            now=ctx.now,
        )

    # 4. Post-commit side-effects — OUTSIDE the write lock so they can open their
    #    own sessions (the writer lock is not re-entrant): change-5 failure loop
    #    on a corrupt archive, or FRG-DL-010 client cleanup on success.
    if final_state is TrackedDownloadState.IMPORTED:
        await _post_import_cleanup(
            db, settings, client_id=client_id, download_id=download_id
        )
    elif final_state is TrackedDownloadState.FAILED_PENDING:
        await process_failures(db, commands=commands, settings=settings, now=ctx.now)

    return final_state


async def _reconcile_recovered_import(
    db: Database,
    ctx: ImportContext,
    *,
    row_id: int,
    download_id: str,
    series_id: int | None,
    issue_id: int | None,
) -> TrackedDownloadState | None:
    """Reconcile a stale ``importing`` row whose source path is now empty.

    A crashed run can leave the file already moved into the library (FS,
    irreversible) while its ``issue_files``/history/state writes rolled back. We
    detect that on disk instead of blindly downgrading to ``import_blocked``:

    - if an ``issue_files`` row already covers a still-present file for the
      resolved issue, the import is durable → just advance to ``imported``;
    - else if an orphaned file carrying this issue's ``[__issueid__]`` identity
      tag sits in the series folder (the moved-but-unrecorded file), adopt it:
      create the ``issue_files`` row + an ``imported`` history event and advance.

    Returns the terminal state applied, or ``None`` when nothing is recoverable
    (caller then leaves the row ``importing`` for a later retry rather than
    orphaning the move).
    """
    if issue_id is None:
        return None
    async with db.read_session() as session:
        issue = await session.get(IssueRow, issue_id)
        if issue is None:
            return None
        series = await session.get(SeriesRow, issue.series_id)
        if series is None:
            return None
        linked = (
            (
                await session.execute(
                    select(IssueFileRow.path).where(IssueFileRow.issue_id == issue_id)
                )
            )
            .scalars()
            .all()
        )
        series_path = series.path
        resolved_series_id = series_id if series_id is not None else issue.series_id

    linked_paths = set(linked)
    # Case A: a recorded file for this issue still exists → import already durable.
    existing = next((p for p in linked_paths if os.path.exists(p)), None)
    if existing is not None:
        async with db.write_session() as session:
            await _apply_state(
                session, row_id, TrackedDownloadState.IMPORTED, TRACKED_STATUS_OK, [], ctx.now
            )
            await apply_source_import(
                session,
                download_id=download_id,
                final_state=TrackedDownloadState.IMPORTED,
                imported_issues=[(issue_id, existing)],
                now=ctx.now,
            )
        return TrackedDownloadState.IMPORTED

    # Case B: an orphaned moved file carrying this issue's id tag → adopt it.
    tag = f"[__{issue_id}__]"
    adopted: str | None = None
    try:
        entries = os.listdir(series_path) if os.path.isdir(series_path) else []
    except OSError:
        entries = []
    for name in entries:
        full = os.path.join(series_path, name)
        if tag in name and full not in linked_paths and os.path.isfile(full):
            adopted = full
            break
    if adopted is None:
        return None

    async with db.write_session() as session:
        size = os.path.getsize(adopted)
        await repo.add_issue_file(
            session, issue_id=issue_id, path=adopted, size=size, added_at=ctx.now
        )
        history.record_event(
            session,
            event_type=history.EVENT_IMPORTED,
            series_id=resolved_series_id,
            issue_id=issue_id,
            download_id=download_id,
            source=history.SOURCE_DOWNLOAD,
            data={"reconciled": True, "imported_path": adopted},
            now=ctx.now,
        )
        await _apply_state(
            session, row_id, TrackedDownloadState.IMPORTED, TRACKED_STATUS_OK, [], ctx.now
        )
        await apply_source_import(
            session,
            download_id=download_id,
            final_state=TrackedDownloadState.IMPORTED,
            imported_issues=[(issue_id, adopted)],
            now=ctx.now,
        )
    logger.info(
        "process-imports: recovered orphaned import for download %s -> %s",
        download_id,
        adopted,
    )
    return TrackedDownloadState.IMPORTED


def _resolve_final(
    candidates, outcomes: list[ImportOutcome], *, no_output: bool
) -> tuple[TrackedDownloadState, str, list[str]]:
    """Fold per-file outcomes into one tracked (state, status, messages) verdict.

    Precedence: any corrupt/invalid archive fails the whole download (→ change-5
    failed handling); otherwise every file must import for ``imported``; anything
    short of that (including zero importable files) blocks with per-file reasons —
    never lost (FRG-DL-009).
    """
    if no_output or not outcomes:
        return (
            TrackedDownloadState.IMPORT_BLOCKED,
            TRACKED_STATUS_WARNING,
            ["no importable files found under the completed download path"],
        )
    if any(o.status is ImportStatus.FAILED for o in outcomes):
        messages = [
            f"{o.candidate.file_name}: {reason}"
            for o in outcomes
            if o.status is ImportStatus.FAILED
            for reason in (o.reasons or ("archive failed validation",))
        ]
        return TrackedDownloadState.FAILED_PENDING, TRACKED_STATUS_ERROR, messages
    if all(o.status is ImportStatus.IMPORTED for o in outcomes):
        return TrackedDownloadState.IMPORTED, TRACKED_STATUS_OK, []
    messages = [
        f"{o.candidate.file_name}: {reason}"
        for o in outcomes
        if o.status is ImportStatus.BLOCKED
        for reason in (o.reasons or ("blocked",))
    ]
    return TrackedDownloadState.IMPORT_BLOCKED, TRACKED_STATUS_WARNING, messages


async def _apply_state(
    session: AsyncSession,
    row_id: int,
    final_state: TrackedDownloadState,
    status: str,
    messages: list[str],
    now: dt.datetime,
) -> None:
    """Write the terminal tracked-download transition inside the caller's session.

    Lands in the SAME transaction as the pipeline's issue_files/history rows, so
    the queue state and the imported file commit atomically. A row de-tracked
    mid-flight (manual queue remove) is left alone.
    """
    row = await session.get(TrackedDownloadRow, row_id)
    if row is None:
        return
    row.state = final_state.value
    row.status = status
    row.status_messages = _encode_messages(messages)
    row.updated_at = now
    queue_event(
        session,
        TrackedStateChanged(
            download_id=row.download_id,
            state=row.state,
            status=row.status,
            series_id=row.series_id,
            issue_id=row.issue_id,
        ),
    )


async def _post_import_cleanup(
    db: Database,
    settings: Settings | None,
    *,
    client_id: int | None,
    download_id: str,
) -> None:
    """Remove or mark-imported the client item after a successful import (FRG-DL-010).

    Gated on the per-client ``remove_completed_downloads`` flag: enabled →
    ``remove(item, delete_data=True)`` (which also drops DDL staging, since that
    only happens after import success); disabled → ``mark_imported(item)`` so the
    item is never reprocessed but its data (and DDL staging) is retained. Purely
    best-effort — a client hiccup must never undo the durable import.
    """
    if client_id is None:
        return
    async with db.read_session() as session:
        client_row = await session.get(DownloadClientRow, client_id)
    remove_completed = bool(
        client_row.remove_completed_downloads if client_row is not None else False
    )
    try:
        client = await build_client_for_id(db, client_id, settings=settings)
        if client is None:
            return
        for item in await client.get_items():
            if item.download_id != download_id:
                continue
            if remove_completed:
                await client.remove(item, delete_data=True)
            else:
                await client.mark_imported(item)
            return
    except Exception:  # noqa: BLE001 — cleanup failure must not undo the import
        logger.warning(
            "process-imports: post-import client cleanup failed; import stands",
            extra={"client_id": client_id, "download_id": download_id},
        )


__all__ = [
    "PROCESS_IMPORTS_INTERVAL",
    "PROCESS_IMPORTS_MIN_INTERVAL",
    "PROCESS_IMPORTS_TASK",
    "ProcessImportsCommand",
    "build_import_context",
    "process_imports",
]
