"""The single shared import pipeline (FRG-PP-001).

One pipeline serves both M1 sources — completed-download import and per-series
rescan — as four source-agnostic stages:

    gather(source)      -> ImportCandidate[]   (per-source intake; the ONLY fork)
    aggregate(candidate)-> Evidence            (parse evidence, one parser)
    decide(evidence)    -> ImportDecision       (ordered specs, all run)
    execute(approved)   -> ExecuteResult        (safe file ops + issue_files row)

There is exactly one :func:`decide`/:func:`decide`-driven and one
:func:`execute` implementation; the source is represented as data on
:class:`~foragerr.importer.sources.ImportCandidate` (``source_kind``), never as a
branch in decision or file-op logic (FRG-PP-001 scenario 2).

Intended entry points for the flows commands (``ProcessImportsCommand`` /
``RescanSeriesCommand`` — implemented by the flows agent, not here):

- :func:`gather` — run a source's intake against an open session + context.
- :func:`import_candidate` — aggregate → decide → execute one candidate,
  writing the ``issue_files`` row and the ``import_history`` event **inside the
  caller's ``write_session``** (FRG-PP-011), and returning an
  :class:`ImportOutcome`. It returns IMPORTED / BLOCKED / FAILED; it never
  mutates ``tracked_downloads`` — the flows command owns that state machine and
  applies the status-guarded ``import_pending → importing → imported`` /
  ``import_blocked`` transitions from the outcome (change-5 concurrency seam).

Blocked/failed items are never lost and never auto-deleted (FRG-PP-005): they
persist as an ``import_blocked`` / ``import_failed`` history row with reasons and
leave the source file in place.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from foragerr.importer import fileops, history
from foragerr.importer.context import ImportContext
from foragerr.importer.decisions import ImportDecision, ImportEvaluation, decide
from foragerr.importer.evidence import Evidence, aggregate
from foragerr.importer.models import ImportHistoryRow
from foragerr.naming import RenameFields, render_filename
from foragerr.importer.sources import (
    SOURCE_DOWNLOAD,
    CompletedDownloadSource,
    ImportCandidate,
    RescanSource,
)
from foragerr.library import matching, repo
from foragerr.library.models import IssueFileRow, IssueRow, SeriesRow
from foragerr.parser.result import Booktype, IssueClassification
from foragerr.quality.models import FormatProfileRow, decode_formats
from foragerr.security.archives import inspect_archive
from foragerr.security.paths import safe_join

logger = logging.getLogger("foragerr.importer.pipeline")

# --- outcome types -----------------------------------------------------------


class ImportStatus(Enum):
    """The terminal verdict :func:`import_candidate` reports back to the flows."""

    IMPORTED = "imported"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ImportOutcome:
    """What one candidate resolved to (FRG-PP-001)."""

    status: ImportStatus
    candidate: ImportCandidate
    reasons: tuple[str, ...] = ()
    series_id: int | None = None
    issue_id: int | None = None
    issue_file_id: int | None = None
    imported_path: str | None = None
    quarantine_path: str | None = None
    upgraded: bool = False


@dataclass(frozen=True, slots=True)
class ExecuteResult:
    imported_path: str
    issue_file_id: int
    size: int
    quarantine_path: str | None
    upgraded: bool


async def _run_fs(ctx: ImportContext, func, *args, **kwargs):
    """Run a blocking filesystem op through the context's offload seam.

    The heavy import file operations (``place_file``'s multi-GB copy + fsync,
    archive inspection) are synchronous and filesystem-only. When the flows
    command wired ``ctx.offload`` they run on a daemon thread so the shared event
    loop keeps serving; direct callers (tests) leave it ``None`` and run inline.
    The database work stays on the loop/session — only the FS portion offloads.
    """
    if ctx.offload is not None:
        return await ctx.offload(func, *args, **kwargs)
    return func(*args, **kwargs)


# --- stage 1: gather ---------------------------------------------------------


async def gather(
    source: CompletedDownloadSource | RescanSource,
    session: AsyncSession,
    ctx: ImportContext,
) -> list[ImportCandidate]:
    """Run a source's intake (FRG-PP-001). The source is data; this dispatch is
    the only place the two M1 intakes differ."""
    return await source.gather(session, ctx)


# --- stage 2: aggregate ------------------------------------------------------


def aggregate_candidate(candidate: ImportCandidate, ctx: ImportContext) -> Evidence:
    """Aggregate parse evidence for one candidate (FRG-PP-004)."""
    return aggregate(
        grab_title=candidate.grab_title,
        file_name=candidate.file_name,
        folder_name=candidate.folder_name,
        client_title=candidate.client_title,
        reference_year=ctx.reference_year,
    )


# --- reconciliation (FRG-PP-003) --------------------------------------------


async def _issue_index_for_series(
    session: AsyncSession, series_id: int, ctx: ImportContext
) -> list:
    """The series' parsed-issue index, built once per run (FRG-PP-003).

    Cached on the run-scoped :class:`ImportContext` so a multi-candidate drain /
    rescan parses each series' issue numbers once, not once per candidate."""
    index = ctx.issue_index_cache.get(series_id)
    if index is None:
        issues = await repo.list_issues_for_series(session, series_id)
        index = matching.build_issue_index(issues)
        ctx.issue_index_cache[series_id] = index
    return index


async def _match_issue_in_series(
    session: AsyncSession, series_id: int, issue, ctx: ImportContext
) -> int | None:
    return matching.match_issue_id(
        issue, await _issue_index_for_series(session, series_id, ctx)
    )


async def reconcile(
    session: AsyncSession,
    candidate: ImportCandidate,
    evidence: Evidence,
    ctx: ImportContext,
) -> tuple[int | None, int | None]:
    """Resolve (series_id, issue_id) for a candidate (FRG-PP-003).

    Priority: embedded ``[__issueid__]`` tag (direct lookup, DDL handshake) >
    grab-history reconciliation by download id > parser heuristic (matching key +
    issue number, scoped to the rescan series when present).
    """
    # 1. issue-id tag short-circuit.
    if evidence.issue_id:
        try:
            iid = int(evidence.issue_id)
        except (TypeError, ValueError):
            iid = None
        if iid is not None:
            issue_row = await session.get(IssueRow, iid)
            if issue_row is not None:
                # On a scoped rescan the tag is only trustworthy for THIS series:
                # a file carrying another series' id tag (misfiled, or a stale
                # tag) must not be dragged into the scoped series' folder
                # (FRG-SER-010). Fall through to the heuristic when it disagrees.
                if (
                    candidate.series_scope_id is None
                    or issue_row.series_id == candidate.series_scope_id
                ):
                    return issue_row.series_id, issue_row.id

    # 2. grab-history reconciliation by download id (survives an unparseable name).
    if candidate.grab_series_id is not None and candidate.grab_issue_id is not None:
        return candidate.grab_series_id, candidate.grab_issue_id

    # 3. parser heuristic.
    if evidence.issue is None:
        return None, None
    if candidate.series_scope_id is not None:
        series = await session.get(SeriesRow, candidate.series_scope_id)
        if series is None or not matching.series_title_matches(
            evidence.matching_key, series.matching_key
        ):
            return None, None
        issue_id = await _match_issue_in_series(session, series.id, evidence.issue, ctx)
        return (series.id, issue_id) if issue_id is not None else (None, None)

    if evidence.matching_key is None:
        return None, None
    series = (
        await session.execute(
            select(SeriesRow).where(SeriesRow.matching_key == evidence.matching_key)
        )
    ).scalars().first()
    if series is None:
        return None, None
    issue_id = await _match_issue_in_series(session, series.id, evidence.issue, ctx)
    return (series.id, issue_id) if issue_id is not None else (None, None)


# --- stage 3 prep: build the once-computed evaluation ------------------------


def _ext(name: str) -> str | None:
    suffix = Path(name).suffix.lstrip(".").lower()
    return suffix or None


async def _already_imported(
    session: AsyncSession, download_id: str | None, issue_id: int | None
) -> bool:
    if not download_id or issue_id is None:
        return False
    count = await session.scalar(
        select(func.count())
        .select_from(ImportHistoryRow)
        .where(
            ImportHistoryRow.download_id == download_id,
            ImportHistoryRow.issue_id == issue_id,
            ImportHistoryRow.event_type.in_(
                (history.EVENT_IMPORTED, history.EVENT_UPGRADE_REPLACED)
            ),
        )
    )
    return bool(count)


async def build_evaluation(
    session: AsyncSession,
    candidate: ImportCandidate,
    evidence: Evidence,
    ctx: ImportContext,
) -> ImportEvaluation:
    """Compute the once-per-candidate derived facts for :func:`decide`."""
    if candidate.mapping_warning is not None:
        return ImportEvaluation(
            evidence=evidence,
            size=candidate.size,
            mapping_warning=candidate.mapping_warning,
            junk_size_floor=ctx.junk_size_floor_bytes,
        )

    series_id, issue_id = await reconcile(session, candidate, evidence, ctx)

    archive = None
    if os.path.exists(candidate.local_path):
        # Archive inspection reads the whole central directory off disk; run it
        # off the event loop when an offload seam is wired (FRG-PP-006).
        archive = await _run_fs(ctx, inspect_archive, candidate.local_path)

    existing_path: str | None = None
    existing_format: str | None = None
    ladder: tuple[str, ...] = ()
    dest_dir = ctx.library_root
    if series_id is not None:
        series = await session.get(SeriesRow, series_id)
        if series is not None:
            dest_dir = series.path
            profile = await session.get(FormatProfileRow, series.format_profile_id)
            if profile is not None:
                ladder = tuple(decode_formats(profile.formats))
    if issue_id is not None:
        existing = (
            await session.execute(
                select(IssueFileRow)
                .where(IssueFileRow.issue_id == issue_id)
                .order_by(IssueFileRow.id)
            )
        ).scalars().first()
        if existing is not None:
            existing_path = existing.path
            existing_format = _ext(existing.path)

    free = ctx.free_space_probe(dest_dir or ctx.library_root)

    return ImportEvaluation(
        evidence=evidence,
        size=candidate.size,
        series_id=series_id,
        issue_id=issue_id,
        archive=archive,
        existing_file_path=existing_path,
        existing_format=existing_format,
        new_format=_ext(candidate.file_name),
        format_ladder=ladder,
        free_bytes=free,
        needed_bytes=candidate.size,
        margin_bytes=ctx.free_space_margin_bytes,
        already_imported=await _already_imported(session, candidate.download_id, issue_id),
        junk_size_floor=ctx.junk_size_floor_bytes,
    )


# --- rename field construction ----------------------------------------------


def _classification_label(issue: IssueRow, evidence: Evidence) -> str | None:
    """Annual/Special rendering token, from the stored issue type or parse."""
    if issue.issue_type and issue.issue_type != "regular":
        return issue.issue_type.capitalize()
    ev_issue = evidence.issue
    if ev_issue is not None and ev_issue.classification is not IssueClassification.REGULAR:
        return ev_issue.classification.value.capitalize()
    return None


def build_fields(series: SeriesRow, issue: IssueRow, evidence: Evidence) -> RenameFields:
    """Assemble the renamer token values for one issue (FRG-PP-009)."""
    year = series.start_year
    booktype = evidence.booktype
    return RenameFields(
        series_title=series.title,
        series_cleantitle=series.matching_key,
        volume=str(evidence.volume_ordinal) if evidence.volume_ordinal else None,
        year=str(year) if year is not None else None,
        issue=issue.issue_number,
        issue_title=issue.title,
        classification=_classification_label(issue, evidence),
        booktype=None if booktype is Booktype.ISSUE else booktype.value,
        release_group=evidence.release_group,
        # Internal IssueRow.id — the same id the DDL name builder embeds in its
        # ``[__issueid__]`` handshake tag and that :func:`reconcile` looks up by
        # primary key, so a renamed file re-imports to the same issue.
        issue_id=str(issue.id),
        publisher=series.publisher,
    )


# --- stage 4: execute --------------------------------------------------------


async def execute(
    session: AsyncSession,
    candidate: ImportCandidate,
    ev: ImportEvaluation,
    ctx: ImportContext,
) -> ExecuteResult:
    """Rename into the library, place the file safely, swap the issue_files row.

    **FS↔DB ordering (FRG-PP-010).** The irreversible on-disk move happens FIRST
    (``place_file``); only after it succeeds is any DB row mutated and, on an
    upgrade, the superseded file quarantined (never deleted). This makes every
    interruption point recoverable:

    - a ``place_file`` failure raises before any DB write or quarantine, so the
      row still points at the (untouched) old file — nothing to reconcile;
    - once the new file is placed, a later failure rolls the row changes back but
      leaves the placed file carrying its ``[__issueid__]`` identity tag on disk,
      which re-claim / rescan reconciles back to this issue rather than orphaning.

    The reverse (old order) quarantined + dropped the old row *before* placing,
    so a ``place_file`` failure rolled back the restored old row while the file
    was already gone — a vanished path that the next rescan removed, silently
    reverting the issue to Wanted. The FS-heavy copy runs through ``ctx.offload``.
    """
    assert ev.series_id is not None and ev.issue_id is not None
    series = await session.get(SeriesRow, ev.series_id)
    issue = await session.get(IssueRow, ev.issue_id)
    assert series is not None and issue is not None

    fields = build_fields(series, issue, ev.evidence)
    ext = Path(candidate.file_name).suffix
    new_name = render_filename(
        fields,
        template=ctx.file_template,
        ext=ext,
        enabled=ctx.rename_enabled,
        original=candidate.file_name,
    )
    # Destination directory: the series' own (template-derived) folder; created
    # via safe_join so the constructed path can never escape the series root.
    dest_path = safe_join(series.path, new_name)

    # 1. IRREVERSIBLE MOVE FIRST — before any DB mutation or quarantine, off the
    #    event loop. os.replace overwrites an existing destination, so placing
    #    ahead of the row swap never collides.
    placed = await _run_fs(
        ctx,
        fileops.place_file,
        candidate.local_path,
        dest_path,
        mode=ctx.transfer_mode,
        margin_bytes=ctx.free_space_margin_bytes,
    )
    size = placed.stat().st_size

    # 2. Only now that the new file is durable: send the superseded file to the
    #    recycle bin (FRG-PP-013) — or permanently delete it when no bin is
    #    configured — and drop its stale row, then add the new row. If any of
    #    this rolls back, the placed file's id tag keeps it recoverable.
    quarantine_path: str | None = None
    upgraded = False
    if (
        ev.existing_file_path is not None
        and ev.existing_file_path != str(placed)
        and os.path.exists(ev.existing_file_path)
    ):
        if ctx.recycle_bin_path:
            quarantine_path = str(
                await _run_fs(
                    ctx,
                    fileops.recycle_file,
                    ev.existing_file_path,
                    ctx.recycle_bin_path,
                    now=ctx.now,
                )
            )
        else:
            # No bin configured: permanently delete the replaced file, but still
            # record the replacement (with no recycle path) on the history event.
            await _run_fs(ctx, os.remove, ev.existing_file_path)
            quarantine_path = None
        upgraded = True
        old_row = (
            await session.execute(
                select(IssueFileRow).where(IssueFileRow.path == ev.existing_file_path)
            )
        ).scalars().first()
        if old_row is not None:
            await session.delete(old_row)
            await session.flush()

    # 3. Move-mode: clean up emptied source directories up to the staging root.
    if (
        ctx.transfer_mode is fileops.TransferMode.MOVE
        and candidate.container_root
        and candidate.source_kind == SOURCE_DOWNLOAD
    ):
        source_parent = Path(candidate.local_path).parent
        if str(source_parent) != candidate.container_root:
            await _run_fs(
                ctx,
                fileops.cleanup_empty_dirs,
                source_parent,
                candidate.container_root,
            )

    file_row = await repo.add_issue_file(
        session, issue_id=issue.id, path=str(placed), size=size, added_at=ctx.now
    )
    return ExecuteResult(
        imported_path=str(placed),
        issue_file_id=file_row.id,
        size=size,
        quarantine_path=quarantine_path,
        upgraded=upgraded,
    )


# --- the driven whole: aggregate -> decide -> execute ------------------------


def _source_provenance(candidate: ImportCandidate) -> str:
    return (
        history.SOURCE_DOWNLOAD
        if candidate.source_kind == SOURCE_DOWNLOAD
        else history.SOURCE_RESCAN
    )


def _source_title(candidate: ImportCandidate) -> str:
    return candidate.grab_title or candidate.client_title or candidate.file_name


async def import_candidate(
    session: AsyncSession, candidate: ImportCandidate, ctx: ImportContext
) -> ImportOutcome:
    """Aggregate → decide → execute one candidate, recording history (FRG-PP-001).

    Writes the ``import_history`` event (and, on success, the ``issue_files``
    row) inside the caller's ``write_session`` (FRG-PP-011). Returns the outcome;
    does not touch ``tracked_downloads`` — the flows command applies the state
    transition from the returned :class:`ImportStatus`.

    **Candidate isolation (FRG-DL-009 / FRG-PP-002).** The decide+execute+row
    write for one candidate runs inside a per-candidate SAVEPOINT
    (``begin_nested``), and any exception escaping ``execute`` (a filesystem IO
    failure) is caught and turned into a BLOCKED outcome. Together these ensure a
    failure in one candidate can neither escape to unwind the shared
    ``write_session`` (which would roll back an already-moved sibling's
    ``issue_files`` row, orphaning its file) nor leave the session poisoned for
    the candidates that follow it. The moved-but-failed file keeps its identity
    tag on disk and is reconciled on the next run.
    """
    evidence = aggregate_candidate(candidate, ctx)
    try:
        async with session.begin_nested():  # SAVEPOINT isolating this candidate
            ev = await build_evaluation(session, candidate, evidence, ctx)
            decision: ImportDecision = decide(ev)

            data = {
                "provenance": dict(evidence.provenance),
                "source_kind": candidate.source_kind,
            }

            if not decision.approved:
                data["reasons"] = list(decision.reasons)
                failed = decision.failed
                history.record_event(
                    session,
                    event_type=(
                        history.EVENT_IMPORT_FAILED
                        if failed
                        else history.EVENT_IMPORT_BLOCKED
                    ),
                    series_id=decision.series_id,
                    issue_id=decision.issue_id,
                    download_id=candidate.download_id,
                    source_title=_source_title(candidate),
                    source=_source_provenance(candidate),
                    data=data,
                    now=ctx.now,
                )
                return ImportOutcome(
                    status=ImportStatus.FAILED if failed else ImportStatus.BLOCKED,
                    candidate=candidate,
                    reasons=decision.reasons,
                    series_id=decision.series_id,
                    issue_id=decision.issue_id,
                )

            result = await execute(session, candidate, ev, ctx)
            data["imported_path"] = result.imported_path
            data["size"] = result.size
            history.record_event(
                session,
                event_type=(
                    history.EVENT_UPGRADE_REPLACED
                    if result.upgraded
                    else history.EVENT_IMPORTED
                ),
                series_id=ev.series_id,
                issue_id=ev.issue_id,
                download_id=candidate.download_id,
                source_title=_source_title(candidate),
                source=_source_provenance(candidate),
                data=data,
                quarantine_path=result.quarantine_path,
                now=ctx.now,
            )
            return ImportOutcome(
                status=ImportStatus.IMPORTED,
                candidate=candidate,
                series_id=ev.series_id,
                issue_id=ev.issue_id,
                issue_file_id=result.issue_file_id,
                imported_path=result.imported_path,
                quarantine_path=result.quarantine_path,
                upgraded=result.upgraded,
            )
    except Exception as exc:  # noqa: BLE001 — an IO failure must not escape/roll siblings
        # The SAVEPOINT already rolled back this candidate's DB writes; siblings
        # committed earlier in the shared session are untouched. Park it as
        # BLOCKED (not FAILED: an environmental IO error is not a bad release, so
        # it must not blocklist + re-search) with a visible reason, and re-record
        # the block in the now-clean outer transaction so it persists.
        logger.warning(
            "import: candidate %s failed during execute; blocked (not lost): %s",
            candidate.file_name,
            exc,
        )
        reason = f"import failed placing the file on disk: {exc}"
        history.record_event(
            session,
            event_type=history.EVENT_IMPORT_BLOCKED,
            download_id=candidate.download_id,
            source_title=_source_title(candidate),
            source=_source_provenance(candidate),
            data={
                "provenance": dict(evidence.provenance),
                "source_kind": candidate.source_kind,
                "reasons": [reason],
                "error": str(exc),
            },
            now=ctx.now,
        )
        return ImportOutcome(
            status=ImportStatus.BLOCKED,
            candidate=candidate,
            reasons=(reason,),
        )


__all__ = [
    "ExecuteResult",
    "ImportOutcome",
    "ImportStatus",
    "aggregate_candidate",
    "build_evaluation",
    "build_fields",
    "execute",
    "gather",
    "import_candidate",
    "reconcile",
]
