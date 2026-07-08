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
from foragerr.importer.decisions import (
    ImportDecision,
    ImportEvaluation,
    decide,
    duplicate_win_reason,
    same_rung,
)
from foragerr.importer.evidence import (
    PROV_COMICINFO,
    PROV_COMICINFO_CONFLICT,
    PROV_MANUAL_OVERRIDE,
    Evidence,
    aggregate,
)
from foragerr.importer.models import ImportHistoryRow
from foragerr.naming import RenameFields, render_filename
from foragerr.importer.sources import (
    SOURCE_DOWNLOAD,
    SOURCE_LIBRARY,
    SOURCE_MANUAL,
    SOURCE_RESCAN,
    CompletedDownloadSource,
    ImportCandidate,
    LibraryImportSource,
    ManualImportSource,
    ManualOverride,
    RescanSource,
)
from foragerr.library import matching, repo
from foragerr.library.models import IssueFileRow, IssueRow, SeriesRow
from foragerr.metadata.comicinfo import (
    build_comicinfo_bytes,
    read_embedded_metadata,
    tag_cbz,
)
from foragerr.parser import parse
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
    #: Why the incoming file won a same-rung duplicate tie (FRG-PP-014), or
    #: ``None`` for a fresh import / profile-order upgrade. Recorded on the
    #: replacement history event so the outcome and its reason are visible.
    duplicate_reason: str | None = None


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
    source: (
        CompletedDownloadSource
        | RescanSource
        | ManualImportSource
        | LibraryImportSource
    ),
    session: AsyncSession,
    ctx: ImportContext,
) -> list[ImportCandidate]:
    """Run a source's intake (FRG-PP-001). The source is data; this dispatch is
    the only place the intakes differ."""
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


async def _resolve_override(
    session: AsyncSession, candidate: ImportCandidate, override: ManualOverride
) -> tuple[int, int] | None:
    """Validate a manual override against real rows (FRG-PP-016, decision 2).

    Returns the pinned ``(series_id, issue_id)`` only when the override names a
    real issue that (when a series is also named) belongs to it AND — in a scoped
    context — is in scope. An override naming a non-existent or mismatched entity
    returns ``None`` (dropped, not trusted) so the file falls back to the
    heuristic rather than fabricating a mapping. A series-only override cannot
    resolve a concrete issue here; :func:`reconcile` handles it separately
    (series pinned, issue matched heuristically within it — FRG-IMP-023).
    """
    if override.issue_id is None:
        return None
    issue_row = await session.get(IssueRow, override.issue_id)
    if issue_row is None:
        return None
    if override.series_id is not None and issue_row.series_id != override.series_id:
        return None  # issue does not belong to the named series → not trusted
    if (
        candidate.series_scope_id is not None
        and issue_row.series_id != candidate.series_scope_id
    ):
        return None  # out of scope for a series-pinned manual folder
    return issue_row.series_id, issue_row.id


async def _resolve_series_override(
    session: AsyncSession, candidate: ImportCandidate, override: ManualOverride
) -> int | None:
    """Validate a SERIES-ONLY override: the pinned series id, or ``None``.

    A series-only override (a library-import group's confirmed volume,
    FRG-IMP-023) pins WHICH series the file belongs to — human intent beats the
    filename's series parse, exactly like a full override — while the concrete
    issue mapping stays heuristic/embedded within that series. Same trust rules
    as :func:`_resolve_override`: a non-existent series, or one outside a scoped
    candidate's scope, is dropped rather than trusted.
    """
    if override.series_id is None or override.issue_id is not None:
        return None
    series = await session.get(SeriesRow, override.series_id)
    if series is None:
        return None
    if (
        candidate.series_scope_id is not None
        and series.id != candidate.series_scope_id
    ):
        return None
    return series.id


async def _embedded_issue(session: AsyncSession, embedded) -> IssueRow | None:
    """The library issue an embedded ComicVine id resolves to, or ``None``.

    Looks up the ``cv_issue_id`` namespace (distinct from the internal
    ``[__issueid__]`` tag). A parse-degraded or id-less embedded read resolves to
    nothing (FRG-IMP-024)."""
    if embedded is None or embedded.parse_error or embedded.cv_issue_id is None:
        return None
    return (
        await session.execute(
            select(IssueRow).where(IssueRow.cv_issue_id == embedded.cv_issue_id)
        )
    ).scalars().first()


async def _filename_series_match(
    session: AsyncSession, candidate: ImportCandidate, evidence: Evidence
) -> int | None:
    """The series the pure filename heuristic strongly matches, or ``None``.

    Used only for embedded-id conflict detection (FRG-IMP-024): a strong filename
    match to a *different* series than a resolvable embedded id is a conflict, so
    the embedded id does not silently win."""
    if candidate.series_scope_id is not None:
        series = await session.get(SeriesRow, candidate.series_scope_id)
        if series is not None and matching.series_title_matches(
            evidence.matching_key, series.matching_key
        ):
            return series.id
        return None
    if evidence.matching_key is None:
        return None
    series = (
        await session.execute(
            select(SeriesRow).where(SeriesRow.matching_key == evidence.matching_key)
        )
    ).scalars().first()
    return series.id if series is not None else None


#: How :func:`_reconcile_base` resolved the candidate — the signal that produced
#: the returned mapping. ``TAG``/``GRAB`` are our OWN trusted internal signals
#: (an ``[__issueid__]`` tag we wrote, or a grab record we recorded); ``FILENAME``
#: is the untrusted parse; ``None`` means nothing resolved it. The embedded
#: ComicInfo layer sits ABOVE ``FILENAME`` but BELOW ``TAG``/``GRAB``.
_BASE_TAG = "tag"
_BASE_GRAB = "grab"
_BASE_FILENAME = "filename"


async def reconcile(
    session: AsyncSession,
    candidate: ImportCandidate,
    evidence: Evidence,
    ctx: ImportContext,
    *,
    override: ManualOverride | None = None,
    embedded=None,
) -> tuple[int | None, int | None]:
    """Resolve (series_id, issue_id) for a candidate (FRG-PP-003, FRG-PP-016,
    FRG-IMP-024).

    Confidence order::

        manual override > [__issueid__] tag > grab hints
                        > verified embedded CV id > filename heuristic

    A manual override (validated against real rows) is top priority — human intent
    beats any parse. The embedded ComicVine id is authoritative ONLY over the
    untrusted filename parse: it sits ABOVE the filename heuristic but BELOW our
    own ``[__issueid__]`` tag and grab record. So a correctly-grabbed or id-tagged
    download is NEVER overridden by (and never blocked over) archive metadata —
    the grab/tag wins silently, and a stray embedded id is ignored. The embedded
    layer only affects a file whose sole other evidence is the filename (a rescan
    of untagged files, an arbitrary-folder manual import).

    "Conflict" (→ :class:`EmbeddedIdConflictSpec` block) is raised only when the
    embedded id disagrees with a signal AT OR BELOW its precedence that would
    otherwise have resolved the file — i.e. embedded-vs-filename for a file with
    no tag/grab. It is recorded on the evidence provenance so the file surfaces as
    a review/blocked item rather than a silent mis-file.
    """
    # 1. manual override — top priority (validated, or dropped and fall through).
    if override is not None:
        resolved = await _resolve_override(session, candidate, override)
        if resolved is not None:
            evidence.provenance["series"] = PROV_MANUAL_OVERRIDE
            evidence.provenance["issue"] = PROV_MANUAL_OVERRIDE
            return resolved
        # 1b. series-only override (FRG-IMP-023): the series is pinned by human
        #     intent — bypassing the series-title heuristic entirely, so a
        #     corrected/confirmed volume wins even when the filename disagrees
        #     with the ComicVine title — while the ISSUE mapping keeps ch2's
        #     exact precedence (FRG-IMP-024): a VERIFIED embedded ComicVine id
        #     resolving INSIDE the pinned series beats the filename heuristic
        #     (a mis-numbered file imports as its embedded issue); one
        #     resolving OUTSIDE it never silently wins and never silently
        #     loses — the conflict is recorded so EmbeddedIdConflictSpec
        #     blocks the file for review. No issue match → fall through
        #     (the file blocks visibly as unmatched, never guessed).
        pinned_series = await _resolve_series_override(session, candidate, override)
        if pinned_series is not None:
            issue_row = await _embedded_issue(session, embedded)
            if issue_row is not None and issue_row.series_id == pinned_series:
                evidence.provenance["series"] = PROV_MANUAL_OVERRIDE
                evidence.provenance["issue"] = PROV_COMICINFO
                return pinned_series, issue_row.id
            if issue_row is not None:
                # Resolvable, but to an issue OUTSIDE the human-confirmed
                # series: surface the disagreement (blocks), don't mis-file.
                evidence.provenance[PROV_COMICINFO_CONFLICT] = str(
                    embedded.cv_issue_id
                )
            if evidence.issue is not None:
                issue_id = await _match_issue_in_series(
                    session, pinned_series, evidence.issue, ctx
                )
                if issue_id is not None:
                    evidence.provenance["series"] = PROV_MANUAL_OVERRIDE
                    return pinned_series, issue_id

    base_series, base_issue, base_source = await _reconcile_base(
        session, candidate, evidence, ctx
    )

    # 2. verified embedded ComicVine id — considered ONLY when no trusted internal
    #    signal (our tag / grab record) already resolved the candidate. A tag or
    #    grab is authoritative above the embedded layer: it wins silently and a
    #    differing embedded id is neither an override nor a conflict block.
    if base_source not in (_BASE_TAG, _BASE_GRAB):
        issue_row = await _embedded_issue(session, embedded)
        if issue_row is not None:
            scope_ok = (
                candidate.series_scope_id is None
                or issue_row.series_id == candidate.series_scope_id
            )
            filename_series = await _filename_series_match(session, candidate, evidence)
            filename_conflict = (
                filename_series is not None and filename_series != issue_row.series_id
            )
            if scope_ok and not filename_conflict:
                # Beats the filename heuristic (the only signal below it here).
                evidence.provenance["series"] = PROV_COMICINFO
                evidence.provenance["issue"] = PROV_COMICINFO
                return issue_row.series_id, issue_row.id
            # Resolvable but disagrees with the filename that would otherwise have
            # resolved this untagged/ungrabbed file (or is out of scope): record
            # the conflict so it surfaces as a review item, not a silent mis-file.
            evidence.provenance[PROV_COMICINFO_CONFLICT] = str(embedded.cv_issue_id)

    return base_series, base_issue


async def _reconcile_base(
    session: AsyncSession,
    candidate: ImportCandidate,
    evidence: Evidence,
    ctx: ImportContext,
) -> tuple[int | None, int | None, str | None]:
    """The M1 base resolution: ``[__issueid__]`` tag > grab hints > filename
    heuristic (FRG-PP-003). The override/embedded layers sit above this.

    Returns ``(series_id, issue_id, base_source)`` where ``base_source`` names the
    signal that produced the mapping (:data:`_BASE_TAG` / :data:`_BASE_GRAB` /
    :data:`_BASE_FILENAME`, or ``None`` when nothing resolved). The caller uses it
    to decide whether the embedded ComicInfo id may be consulted at all — a
    tag/grab result is authoritative above the embedded layer."""
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
                    return issue_row.series_id, issue_row.id, _BASE_TAG

    # 2. grab-history reconciliation by download id (survives an unparseable name).
    if candidate.grab_series_id is not None and candidate.grab_issue_id is not None:
        return candidate.grab_series_id, candidate.grab_issue_id, _BASE_GRAB

    # 3. parser heuristic.
    if evidence.issue is None:
        return None, None, None
    if candidate.series_scope_id is not None:
        series = await session.get(SeriesRow, candidate.series_scope_id)
        if series is None or not matching.series_title_matches(
            evidence.matching_key, series.matching_key
        ):
            return None, None, None
        issue_id = await _match_issue_in_series(session, series.id, evidence.issue, ctx)
        return (series.id, issue_id, _BASE_FILENAME) if issue_id is not None else (None, None, None)

    if evidence.matching_key is None:
        return None, None, None
    series = (
        await session.execute(
            select(SeriesRow).where(SeriesRow.matching_key == evidence.matching_key)
        )
    ).scalars().first()
    if series is None:
        return None, None, None
    issue_id = await _match_issue_in_series(session, series.id, evidence.issue, ctx)
    return (series.id, issue_id, _BASE_FILENAME) if issue_id is not None else (None, None, None)


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

    # Archive I/O first: inspection and the embedded ComicInfo read (FRG-IMP-024)
    # both need the archive on disk, and reconcile() consumes the embedded read.
    archive = None
    embedded = None
    if os.path.exists(candidate.local_path):
        # Archive inspection reads the whole central directory off disk; run it
        # off the event loop when an offload seam is wired (FRG-PP-006).
        archive = await _run_fs(ctx, inspect_archive, candidate.local_path)
        # Embedded ComicInfo read is always active (not gated by the tagging
        # toggle); it degrades to None on an unlisted/failed archive.
        embedded = await _run_fs(
            ctx, read_embedded_metadata, candidate.local_path, archive
        )

    series_id, issue_id = await reconcile(
        session,
        candidate,
        evidence,
        ctx,
        override=candidate.override,
        embedded=embedded,
    )

    existing_path: str | None = None
    existing_format: str | None = None
    existing_size: int | None = None
    existing_fix_revision: int | None = None
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
            existing_size = existing.size
            # The existing file's `(fN)` fixed-release marker (FRG-PP-014):
            # the persisted row value first — renaming strips the marker from
            # the placed basename, so the row is the durable carrier — with a
            # stored-basename parse as the legacy-row fallback.
            existing_fix_revision = existing.fix_revision
            if existing_fix_revision is None:
                existing_fix_revision = parse(
                    Path(existing.path).name, reference_year=ctx.reference_year
                ).fix_revision

    free = ctx.free_space_probe(dest_dir or ctx.library_root)

    # A manual format override feeds the upgrade check only (design decision 2).
    override_format = (
        candidate.override.format if candidate.override is not None else None
    )
    new_format = override_format or _ext(candidate.file_name)

    return ImportEvaluation(
        evidence=evidence,
        size=candidate.size,
        series_id=series_id,
        issue_id=issue_id,
        archive=archive,
        existing_file_path=existing_path,
        existing_format=existing_format,
        new_format=new_format,
        format_ladder=ladder,
        free_bytes=free,
        needed_bytes=candidate.size,
        margin_bytes=ctx.free_space_margin_bytes,
        already_imported=await _already_imported(session, candidate.download_id, issue_id),
        junk_size_floor=ctx.junk_size_floor_bytes,
        comic_info_present=embedded is not None and embedded.comic_info_present,
        embedded_cv_issue_id=embedded.cv_issue_id if embedded is not None else None,
        embedded_verified=evidence.provenance.get("issue") == PROV_COMICINFO,
        comicinfo_conflict=PROV_COMICINFO_CONFLICT in evidence.provenance,
        existing_size=existing_size,
        existing_fix_revision=existing_fix_revision,
        new_fix_revision=evidence.fix_revision,
        duplicate_constraint=ctx.duplicate_constraint,
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


def _register_in_place(
    candidate: ImportCandidate, series: SeriesRow, dest_path: Path, ctx: ImportContext
) -> bool:
    """Whether this candidate is registered at its EXISTING path without any
    ``place_file`` (FRG-IMP-023, m2-existing-library-import design decision 4).

    True only for a LIBRARY-IMPORT candidate (``source_kind`` guard, the same
    data-carried discriminator ``execute``'s move-cleanup uses — the decision
    logic itself never forks) in ``library_import_mode == "in_place"`` (the
    default), and only when the file is already where placement would put it:
    its current path IS the computed destination, or — with renaming disabled,
    where the original name is kept — it already lives anywhere under the
    series folder. ``library_import_mode`` is consumed ONLY at this
    library-import placement seam: every other source (download, rescan,
    manual) routes through ``place_file`` exactly as it did before the mode
    existed, so a rescan of a nested file with renaming disabled still moves
    it to its computed destination. ``move`` mode (and every candidate
    arriving from outside the series folder, e.g. a download staging dir)
    routes through ``place_file`` as before.
    """
    if (
        candidate.source_kind != SOURCE_LIBRARY
        or ctx.library_import_mode != "in_place"
    ):
        return False
    local = Path(candidate.local_path)
    if os.path.realpath(local) == os.path.realpath(dest_path):
        return True
    if not ctx.rename_enabled:
        try:
            return local.resolve().is_relative_to(Path(series.path).resolve())
        except OSError:  # pragma: no cover - unresolvable path: fall through
            return False
    return False


def _same_physical_file(a: str, b: str | os.PathLike[str]) -> bool:
    """Whether two paths denote the SAME physical file, symlink-tolerant.

    ``os.path.samefile`` (device+inode) when both paths exist; otherwise (the
    replacement target may not exist yet) a resolved-``realpath`` comparison.
    Raw-string comparison is never enough here: a series path reached through a
    symlinked walk root names the same file under a different string, and
    treating that as "different" disposes of the very file being registered.
    """
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.realpath(a) == os.path.realpath(os.fspath(b))


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

    **The one deliberate exception (FRG-PP-014):** a replacement whose rendered
    destination is the existing file's OWN path (the default template is
    deterministic per issue, so every same-name re-grab replacement lands here).
    Placing first would let ``place_file``'s ``os.replace`` silently overwrite
    the loser — destroying the never-deleted guarantee — so for that case alone
    the loser is disposed of (dump/recycle/delete per the normal rules) BEFORE
    the placement. A crash between the two steps leaves the loser recoverable
    in the dump/recycle bin and the incoming file still in staging; the rolled-
    back row points at the now-vacated path, which the next rescan reconciles.
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

    # Replacement bookkeeping, computed BEFORE anything moves: a replacement
    # whose target is the existing file's own physical path must dispose of the
    # loser first (see the docstring's FRG-PP-014 exception), and an "existing"
    # file that IS the candidate (a symlink-aliased path naming the same inode)
    # must never be disposed of at all — it is the file being imported. All
    # comparisons are physical (samefile/realpath), never raw strings.
    existing = ev.existing_file_path
    existing_present = existing is not None and os.path.exists(existing)
    in_place = _register_in_place(candidate, series, dest_path, ctx)
    source_is_existing = existing_present and _same_physical_file(
        existing, candidate.local_path
    )
    dest_is_existing = (
        existing_present
        and not in_place
        and _same_physical_file(existing, str(dest_path))
    )
    # A replacement at the SAME profile rung is a duplicate resolution
    # (FRG-PP-014) — the decision engine only approves such a candidate when
    # DuplicateConstraintSpec let it win the tie. Its loser goes to the
    # duplicate-dump folder when one is configured; a profile-order UPGRADE
    # keeps the recycle/delete disposal unchanged.
    duplicate_resolution = existing_present and same_rung(ev)
    duplicate_reason = duplicate_win_reason(ev) if duplicate_resolution else None
    quarantine_path: str | None = None
    upgraded = False

    async def _dispose_existing() -> str | None:
        """Dump / recycle / permanently delete the replaced file (FRG-PP-013/014).

        Returns the quarantine destination, or ``None`` for a permanent delete
        (recorded on the history event with no recycle path)."""
        if duplicate_resolution and ctx.duplicate_dump_path:
            return str(
                await _run_fs(
                    ctx, fileops.dump_file, existing, ctx.duplicate_dump_path,
                    now=ctx.now,
                )
            )
        if ctx.recycle_bin_path:
            return str(
                await _run_fs(
                    ctx, fileops.recycle_file, existing, ctx.recycle_bin_path,
                    now=ctx.now,
                )
            )
        await _run_fs(ctx, os.remove, existing)
        return None

    if in_place:
        # In-place library import (FRG-IMP-023): the candidate is registered at
        # its existing path with NO move/copy/rename at all (design decision 4).
        # A tracked existing file that is the SAME physical file as the
        # candidate is the file being registered — nothing to dispose of, only
        # its row is swapped below; a genuinely different file is disposed of
        # per the normal replacement rules.
        placed = Path(candidate.local_path)
        if existing_present:
            if not source_is_existing:
                quarantine_path = await _dispose_existing()
            upgraded = True
    else:
        if dest_is_existing and not source_is_existing:
            # The rendered destination IS the existing file's path: the loser
            # leaves (dump/recycle/delete) BEFORE place_file can overwrite it
            # (FRG-PP-014 — the loser is never silently destroyed). Crash
            # between the steps: loser already safe, incoming still in staging.
            quarantine_path = await _dispose_existing()
        # 1. IRREVERSIBLE MOVE — before any DB mutation and (same-path case
        #    aside) before any disposal, off the event loop (see the
        #    docstring's FRG-PP-010 ordering).
        placed = await _run_fs(
            ctx,
            fileops.place_file,
            candidate.local_path,
            dest_path,
            mode=ctx.transfer_mode,
            margin_bytes=ctx.free_space_margin_bytes,
        )
        # 2. Only now that the new file is durable: send the superseded file to
        #    the recycle bin (FRG-PP-013) — or the duplicate dump, or permanent
        #    deletion when no bin is configured. If any of the row work below
        #    rolls back, the placed file's id tag keeps it recoverable. A
        #    source that IS the tracked existing file (an aliased path being
        #    renamed onto its computed destination) has nothing to dispose of —
        #    the move above already relocated it.
        if existing_present:
            if not dest_is_existing and not source_is_existing:
                quarantine_path = await _dispose_existing()
            upgraded = True
    size = placed.stat().st_size

    # Drop the replaced/stale row so the new insert can never violate the
    # unique-path constraint: after a replacement (including the same-path and
    # aliased-path cases above), and equally when a vanished file's stale row
    # still squats on the exact path just placed.
    if existing is not None and (upgraded or existing == str(placed)):
        old_row = (
            await session.execute(
                select(IssueFileRow).where(IssueFileRow.path == existing)
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
    # Persist the winner's `(fN)` fixed-release marker on the row (FRG-PP-014):
    # renaming strips the marker from the placed basename, so the row — not the
    # on-disk name — is what future duplicate contests read. Legacy rows stay
    # NULL and fall back to the basename parse in build_evaluation.
    file_row.fix_revision = ev.new_fix_revision
    # Cache the OPDS-PSE page count from the archive report the pipeline already
    # produced (FRG-OPDS-009) — no extra archive open. ``image_count`` is exactly
    # the page count for a fully-listed archive; an unlistable one (magic-only
    # cbr/cb7, or none inspected) stays NULL and is resolved lazily on first OPDS
    # access.
    file_row.page_count = (
        ev.archive.image_count
        if ev.archive is not None and ev.archive.listed
        else None
    )
    await session.flush()
    return ExecuteResult(
        imported_path=str(placed),
        issue_file_id=file_row.id,
        size=size,
        quarantine_path=quarantine_path,
        upgraded=upgraded,
        duplicate_reason=duplicate_reason,
    )


# --- the driven whole: aggregate -> decide -> execute ------------------------


#: Provenance ``source`` column value per candidate kind — a data lookup, so the
#: decision and file-op logic never branch on ``source_kind`` (FRG-PP-001).
_PROVENANCE_BY_KIND: dict[str, str] = {
    SOURCE_DOWNLOAD: history.SOURCE_DOWNLOAD,
    SOURCE_RESCAN: history.SOURCE_RESCAN,
    SOURCE_MANUAL: history.SOURCE_MANUAL,
    SOURCE_LIBRARY: history.SOURCE_LIBRARY,
}


def _source_provenance(candidate: ImportCandidate) -> str:
    return _PROVENANCE_BY_KIND.get(candidate.source_kind, history.SOURCE_DOWNLOAD)


async def _tag_comicinfo(
    session: AsyncSession,
    candidate: ImportCandidate,
    ev: ImportEvaluation,
    ctx: ImportContext,
    result: ExecuteResult,
) -> None:
    """Write a ComicInfo.xml tag into the just-placed cbz (FRG-PP-017).

    Runs ONLY after the file is placed and the imported/upgrade history event is
    recorded, so a tagging failure can never unwind a completed import. Gated
    honestly on the tagging toggle AND the archive having passed inspection
    (``safe_to_extract`` — a fully-listed, fully-vetted zip) AND the placed file
    being a ``.cbz``; a magic-only cbr/cb7 or an unvetted archive is never
    rewritten. The rewrite itself is filesystem work, run through ``ctx.offload``.

    A tagging failure is swallowed here: the file lands untagged and a
    ``comicinfo_tag_failed`` warning event is recorded — the import still
    succeeded. This never raises.
    """
    archive = ev.archive
    if not (
        ctx.comicinfo_tag_enabled
        and archive is not None
        and archive.safe_to_extract
        and result.imported_path.lower().endswith(".cbz")
    ):
        return
    try:
        series = await session.get(SeriesRow, ev.series_id)
        issue = await session.get(IssueRow, ev.issue_id)
        if series is None or issue is None:  # defensive; execute already asserted
            return
        xml_bytes = build_comicinfo_bytes(series, issue)
        await _run_fs(ctx, tag_cbz, result.imported_path, xml_bytes)
    except Exception as exc:  # noqa: BLE001 — tagging is best-effort, never fatal
        # Tagging is best-effort AFTER a completed import: any failure here (a
        # cbz rewrite error, an OSError, or a DB error loading the records) must
        # NOT unwind the already-committed import. Catch broadly (Exception, NOT
        # BaseException — cancellation/KeyboardInterrupt still propagate): the
        # placed file is byte-identical (the rewrite unwound its own temp) and
        # stays imported.
        logger.warning(
            "comicinfo: tagging %s failed after import; left untagged: %s",
            result.imported_path,
            exc,
        )
        history.record_event(
            session,
            event_type=history.EVENT_COMICINFO_TAG_FAILED,
            series_id=ev.series_id,
            issue_id=ev.issue_id,
            download_id=candidate.download_id,
            source_title=_source_title(candidate),
            source=_source_provenance(candidate),
            data={
                "provenance": dict(ev.evidence.provenance),
                "source_kind": candidate.source_kind,
                "imported_path": result.imported_path,
                "error": str(exc),
            },
            now=ctx.now,
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
                # Deduped (RISK-040, FRG-API-011): the tracking loop re-feeds a
                # still-blocked download every cycle; an identical repeated
                # outcome for the same download must not accrete another row.
                await history.record_event_deduped(
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
            if result.duplicate_reason is not None:
                # FRG-PP-014: the same-rung duplicate outcome carries its reason
                # into history, mirroring the rejection-side reason list.
                data["duplicate_reason"] = result.duplicate_reason
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
            # ComicInfo tagging (FRG-PP-017) runs AFTER place_file + the
            # issue_files row + the imported event: a tagging failure is caught
            # inside and NEVER unwinds this completed import (records a warning).
            await _tag_comicinfo(session, candidate, ev, ctx, result)
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
        # Deduped like the rejection path above (RISK-040): a persistent IO
        # failure re-blocks identically on every retry cycle.
        await history.record_event_deduped(
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
