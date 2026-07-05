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
from foragerr.importer.renamer import (
    RenameFields,
    render_filename,
    render_series_folder,
)
from foragerr.importer.sources import (
    SOURCE_DOWNLOAD,
    SOURCE_RESCAN,
    CompletedDownloadSource,
    ImportCandidate,
    RescanSource,
)
from foragerr.library import repo
from foragerr.library.models import IssueFileRow, IssueRow, SeriesRow
from foragerr.library.ordering import parse_issue_number
from foragerr.parser.result import Booktype, Issue, IssueClassification
from foragerr.quality.models import FormatProfileRow, decode_formats
from foragerr.security.archives import inspect_archive
from foragerr.security.paths import safe_join

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


def _issue_equal(a: Issue, b: Issue) -> bool:
    return (
        a.value == b.value
        and a.suffix == b.suffix
        and a.is_infinity == b.is_infinity
        and (a.name or None) == (b.name or None)
    )


def _series_title_matches(parsed_key: str | None, series_key: str) -> bool:
    """Exact key, or the parsed key's tokens are a subset of the series key's
    (same asymmetric rule as the change-1 scanner)."""
    if not parsed_key or not series_key:
        return False
    if parsed_key == series_key:
        return True
    return set(parsed_key.split()) <= set(series_key.split())


async def _match_issue_in_series(
    session: AsyncSession, series_id: int, issue: Issue
) -> int | None:
    for row in await repo.list_issues_for_series(session, series_id):
        if _issue_equal(issue, parse_issue_number(row.issue_number)):
            return row.id
    return None


async def reconcile(
    session: AsyncSession, candidate: ImportCandidate, evidence: Evidence
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
                return issue_row.series_id, issue_row.id

    # 2. grab-history reconciliation by download id (survives an unparseable name).
    if candidate.grab_series_id is not None and candidate.grab_issue_id is not None:
        return candidate.grab_series_id, candidate.grab_issue_id

    # 3. parser heuristic.
    if evidence.issue is None:
        return None, None
    if candidate.series_scope_id is not None:
        series = await session.get(SeriesRow, candidate.series_scope_id)
        if series is None or not _series_title_matches(
            evidence.matching_key, series.matching_key
        ):
            return None, None
        issue_id = await _match_issue_in_series(session, series.id, evidence.issue)
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
    issue_id = await _match_issue_in_series(session, series.id, evidence.issue)
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

    series_id, issue_id = await reconcile(session, candidate, evidence)

    archive = None
    if os.path.exists(candidate.local_path):
        archive = inspect_archive(candidate.local_path)

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


def series_dir_under_root(library_root: str, series: SeriesRow) -> Path:
    """Build the series folder path under ``library_root`` via safe_join
    (FRG-PP-010) — the templated folder name from :func:`render_series_folder`."""
    return safe_join(library_root, render_series_folder(series.title, series.start_year))


# --- stage 4: execute --------------------------------------------------------


async def execute(
    session: AsyncSession,
    candidate: ImportCandidate,
    ev: ImportEvaluation,
    ctx: ImportContext,
) -> ExecuteResult:
    """Rename into the library, place the file safely, swap the issue_files row.

    On an upgrade the superseded file is quarantined (never deleted) and its old
    ``issue_files`` row removed in this same transaction (FRG-PP-010). Runs inside
    the caller's ``write_session``: a file-op failure raises and rolls the row
    changes back.
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
    dest_dir = series.path
    dest_path = safe_join(dest_dir, new_name)

    # Upgrade: quarantine the superseded file and drop its row first, so the
    # unique path constraint cannot collide and the swap is atomic in this txn.
    quarantine_path: str | None = None
    upgraded = False
    if ev.existing_file_path is not None and os.path.exists(ev.existing_file_path):
        quarantine_path = str(
            fileops.quarantine_file(ev.existing_file_path, ctx.config_dir, now=ctx.now)
        )
        upgraded = True
        old_row = (
            await session.execute(
                select(IssueFileRow).where(IssueFileRow.path == ev.existing_file_path)
            )
        ).scalars().first()
        if old_row is not None:
            await session.delete(old_row)
            await session.flush()

    placed = fileops.place_file(
        candidate.local_path,
        dest_path,
        mode=ctx.transfer_mode,
        margin_bytes=ctx.free_space_margin_bytes,
    )

    # Move-mode: clean up emptied source directories up to the staging root.
    if (
        ctx.transfer_mode is fileops.TransferMode.MOVE
        and candidate.container_root
        and candidate.source_kind == SOURCE_DOWNLOAD
    ):
        source_parent = Path(candidate.local_path).parent
        if str(source_parent) != candidate.container_root:
            fileops.cleanup_empty_dirs(source_parent, candidate.container_root)

    size = placed.stat().st_size
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
    """
    evidence = aggregate_candidate(candidate, ctx)
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
                history.EVENT_IMPORT_FAILED if failed else history.EVENT_IMPORT_BLOCKED
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
            history.EVENT_UPGRADE_REPLACED if result.upgraded else history.EVENT_IMPORTED
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
    "series_dir_under_root",
]
