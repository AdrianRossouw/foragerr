"""Existing-library mass import: scan staging + bulk execute (FRG-IMP-023).

Two commands around one persisted staging table
(:class:`~foragerr.library.models.LibraryImportGroupRow`, design decision 2):

- ``library-import-scan`` (:func:`scan_library_root`) — walk a root folder with
  the shared junk-aware walk (FRG-IMP-022), reconcile vanished ``issue_files``
  rows (shared :mod:`~foragerr.library.flows.reconcile` helpers), parse every
  still-unmapped file through the shared evidence layers, group by the parser's
  ``matching_key``, and stage PROGRESSIVELY: the staging rows are replaced
  immediately after the walk (carry-forward and already-imported filtering
  happen inside that one write transaction, so review decisions and imports
  made while a scan runs are never reverted), then the per-group ComicVine
  proposal phase (capped per run, plausibility-floored, never auto-picked)
  lands each proposal on its row in its own short write transaction — the UI
  sees groups within seconds and a mid-proposal restart loses only the
  un-proposed matches. Read-only w.r.t. files, so it takes NO file-mutation
  exclusivity group (design decision 3); it runs on the ``pp`` pool. The scan
  fails fast (visible command error) when a ``library-import`` execute holding
  this root's staged group ids is queued or running — replacing the rows would
  invalidate that selection.

- ``library-import`` (:func:`execute_library_import`) — for each SELECTED
  group (selection IS confirmation: a ``proposed`` group with an attached
  proposal auto-confirms, adopting the proposal as its confirmed volume):
  create the series through the existing :func:`add_series` flow
  (``path_override`` = the group's folder when ``library_import_mode`` is
  ``in_place``; the normal root-relative path in ``move`` mode;
  ``enqueue_refresh=False`` because THIS flow awaits the refresh directly —
  exactly one refresh per imported group, never a doubled fetch/scan), then
  run the group's files through the SAME
  :func:`~foragerr.importer.pipeline.import_candidate` pipeline via
  :class:`~foragerr.importer.sources.LibraryImportSource` — same specs, same
  history events. File-mutating, so it shares ``IMPORT_FILE_MUTATION_GROUP``
  with the drain/rescan/rename commands. Outcomes land back on the staging row
  (state + visible message + structured per-file ``rejections``), never
  silently (FRG-IMP-023 scenario 4). Safety rails: a group whose folder IS the
  root folder never becomes a root-swallowing series; a volume whose series
  already exists elsewhere never has files moved at it — the group blocks
  visibly with the files left untouched.

Re-check semantics: re-running the scan for the root. Already-imported files
are dropped at replace time (re-read of ``issue_files`` inside the txn), so a
re-scan after an import never re-stages what landed. Carry-forward by
``matching_key``: confirmed/skipped decisions, attached proposals + display
fields, and no-match answers all persist across re-scans; only groups with NO
prior proposal/no-match answer are (re-)searched, so deferred groups advance
on the next run instead of starving behind the cap, and a ComicVine outage
never wipes existing proposals (a proposal is only overwritten by a successful
new search).

Import-cycle discipline (design decision 8): this module lives in
``library.flows`` and imports ``foragerr.importer``; nothing under
``importer/`` imports it — the source gets the resolved series id injected.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, ClassVar, Literal

from sqlalchemy import delete, func, select

from foragerr.commands.registry import BaseCommand, register_command, register_handler
from foragerr.commands.service import CommandService, HandlerContext
from foragerr.config import Settings
from foragerr.db import CommandRow, Database, utcnow
from foragerr.http import HttpClientFactory
from foragerr.importer import (
    IMPORT_FILE_MUTATION_GROUP,
    ImportContext,
    ImportStatus,
    LibraryImportSource,
    gather,
    import_candidate,
    media_management_fields,
)
from foragerr.importer.evidence import aggregate
from foragerr.importer.context import DEFAULT_MAX_WALK_DEPTH
from foragerr.library import matching
from foragerr.library.flows import reconcile
from foragerr.library.flows._common import SeriesValidationError, comicvine_factory
from foragerr.library.flows.add import add_series
from foragerr.library.flows.refresh import refresh_series
from foragerr.library.models import (
    IssueFileRow,
    IssueRow,
    LibraryImportGroupRow,
    RootFolderRow,
    SeriesRow,
)
from foragerr.metadata import (
    COMICVINE_CREDENTIAL_MESSAGE,
    ComicVineAuthError,
    ComicVineClient,
    ComicVineError,
)
from foragerr.parser.normalize import matching_key as fold_matching_key
from foragerr.parser.vocab import ARCHIVE_EXTENSIONS

logger = logging.getLogger("foragerr.library.flows.library_import")

OffloadFn = Callable[..., Awaitable[Any]]

#: Fallback default for ``Settings.library_import_proposal_cap`` when no
#: settings are wired (bare test contexts): each proposal is a live,
#: politeness-gated ``search_series`` call, so one scan run must not fan out
#: unboundedly. Groups beyond the cap stage as ``proposed`` with no attached
#: match and a visible message — logged, never silent — and pick up a proposal
#: on a later re-scan (carry-forward keeps already-answered groups out of the
#: budget, so deferred groups advance instead of starving).
LIBRARY_IMPORT_PROPOSAL_CAP = 50

#: Fallback default for ``Settings.library_import_similarity_floor`` (FRG-
#: IMP-023 scenario 4): the best search candidate's shared-matching-key
#: ``name_similarity`` must reach the floor or the group stages as
#: ``no_match`` — reviewable, never guessed.
LIBRARY_IMPORT_SIMILARITY_FLOOR = 0.5

#: The static credential-failure wording (m2-lookup-error-surfacing decision
#: 5): the ONE shared sentence, never the exception's own message, so no key
#: material can leak into staging.
_AUTH_FAILED_MESSAGE = f"comicvine search failed: {COMICVINE_CREDENTIAL_MESSAGE}"


class LibraryImportScanBlockedError(RuntimeError):
    """A queued/running ``library-import`` execute still holds staged group ids
    for this root: the scan's delete+reinsert would invalidate its selection
    mid-flight, so the scan fails fast with this clear, user-visible error
    instead (the command row records it verbatim)."""


# --- commands -----------------------------------------------------------------


@register_command
class LibraryImportScanCommand(BaseCommand):
    """Scan a root folder into library-import staging groups (FRG-IMP-023).

    Runs on the ``pp`` pool but takes NO exclusivity group: it is read-only
    with respect to files (its only writes are the vanished-row reconciliation
    and the staging rows), so it may overlap a drain/rescan safely
    (design decision 3)."""

    name: Literal["library-import-scan"] = "library-import-scan"
    workload_class: ClassVar[str] = "pp"
    root_folder_id: int


@register_command
class LibraryImportCommand(BaseCommand):
    """Bulk-import selected staging groups (FRG-IMP-023).

    File-mutating — it places/registers library files — so it shares the
    importer's exclusivity group with the completed-download drain, rescan,
    rename, and manual import: at most one library-mutating command runs at a
    time regardless of the ``pp`` pool size."""

    name: Literal["library-import"] = "library-import"
    workload_class: ClassVar[str] = "pp"
    exclusivity_group: ClassVar[str | None] = IMPORT_FILE_MUTATION_GROUP
    group_ids: list[int]
    format_profile_id: int | None = None
    monitor_strategy: str = "all"
    search_on_add: bool = False


# --- staged-files / rejections codecs -------------------------------------------


def encode_group_files(files: list[tuple[str, int]]) -> str:
    """Canonical-JSON encoding of a group's ``[{path, size}]`` file list."""
    return json.dumps(
        [{"path": path, "size": size} for path, size in files],
        sort_keys=True,
        separators=(",", ":"),
    )


def decode_group_files(raw: str | None) -> list[tuple[str, int]]:
    """Decode a staged file list; a corrupt value degrades to ``[]`` (logged)."""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("library-import: malformed staged file list; treating as empty")
        return []
    if not isinstance(data, list):
        return []
    out: list[tuple[str, int]] = []
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("path"), str):
            out.append((item["path"], int(item.get("size", 0) or 0)))
    return out


def encode_rejections(reasons: list[str]) -> str:
    """Canonical-JSON encoding of a group's per-file blocked-reason list."""
    return json.dumps(list(reasons), separators=(",", ":"))


def decode_rejections(raw: str | None) -> list[str]:
    """Decode the rejections list; a corrupt value degrades to ``[]`` (logged)."""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("library-import: malformed rejections list; treating as empty")
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, str)]


# --- scan ----------------------------------------------------------------------


@dataclass
class _GroupDraft:
    """One in-progress scan group (pre-persistence working state)."""

    matching_key: str
    files: list[tuple[str, int]] = field(default_factory=list)
    parents: list[str] = field(default_factory=list)
    confidences: list[float] = field(default_factory=list)
    #: How many files parsed to a real series key (vs the folder fallback).
    parsed_count: int = 0
    #: Display-form series name for the ComicVine search term.
    term: str | None = None
    state: str = "proposed"
    proposed_cv_volume_id: int | None = None
    confirmed_cv_volume_id: int | None = None
    #: Display details of the proposed volume (name/year/publisher/poster),
    #: captured at proposal time so the review UI needs no CV round-trip.
    proposal_name: str | None = None
    proposal_start_year: int | None = None
    proposal_publisher: str | None = None
    proposal_image_url: str | None = None
    message: str | None = None

    @property
    def folder(self) -> str:
        return os.path.commonpath(self.parents) if self.parents else ""

    @property
    def confidence(self) -> float:
        if not self.confidences:
            return 0.0
        return round(sum(self.confidences) / len(self.confidences), 4)

    @property
    def needs_proposal(self) -> bool:
        """True when no prior/current answer exists: still ``proposed`` with no
        attached match (new group, deferred-over-cap group, or a group whose
        last search errored). Confirmed/skipped/no-match answers and carried
        proposals are never re-searched (proposal-budget starvation guard)."""
        return self.state == "proposed" and self.proposed_cv_volume_id is None


def _draft_for_file(
    groups: dict[str, _GroupDraft], path: str, size: int, reference_year: int
) -> None:
    """Parse one unmapped file and fold it into its group draft."""
    name = os.path.basename(path)
    parent = os.path.dirname(path)
    parent_name = os.path.basename(parent)
    evidence = aggregate(
        file_name=name, folder_name=parent_name or None, reference_year=reference_year
    )
    parsed = evidence.matching_key is not None
    if parsed:
        key = evidence.matching_key
    else:
        # Unparseable file: group by the folded folder name so the whole folder
        # stays together as ONE reviewable no-match group (never dropped).
        key = fold_matching_key(parent_name or name) or (parent_name or name).casefold()
    draft = groups.setdefault(key, _GroupDraft(matching_key=key))
    draft.files.append((path, size))
    draft.parents.append(parent)
    if parsed:
        draft.parsed_count += 1
        series_layer = evidence.provenance.get("series")
        layer_result = evidence.layers.get(series_layer) if series_layer else None
        if layer_result is not None:
            draft.confidences.append(layer_result.confidence)
            if draft.term is None and layer_result.series_name:
                draft.term = layer_result.series_name
    else:
        draft.confidences.append(0.0)


def _carry_forward(draft: _GroupDraft, prior: LibraryImportGroupRow | None) -> None:
    """Fold the persisting group's prior answer into the fresh draft.

    Carried by ``matching_key``: the attached proposal + display fields (for
    EVERY persisting group, so unskip/back-to-review always shows what it
    showed before), the confirmed/skipped decision, and the no-match answer +
    message. A group with a carried answer is never re-searched — only a
    successful NEW search may overwrite a proposal — so re-scans spend the
    proposal budget exclusively on unanswered groups and a ComicVine outage
    can never wipe existing proposals.
    """
    if prior is not None:
        draft.proposed_cv_volume_id = prior.proposed_cv_volume_id
        draft.proposal_name = prior.proposal_name
        draft.proposal_start_year = prior.proposal_start_year
        draft.proposal_publisher = prior.proposal_publisher
        draft.proposal_image_url = prior.proposal_image_url
        if prior.state == "confirmed" and prior.confirmed_cv_volume_id is not None:
            draft.state = "confirmed"
            draft.confirmed_cv_volume_id = prior.confirmed_cv_volume_id
            return
        if prior.state == "skipped":
            draft.state = "skipped"
            return
        if prior.state == "no_match":
            draft.state = "no_match"
            draft.message = prior.message
            return
        if prior.state == "imported":
            # New unmapped files appeared for an already-imported key: propose
            # the same volume again rather than burning a fresh search on it.
            draft.state = "proposed"
            if draft.proposed_cv_volume_id is None:
                draft.proposed_cv_volume_id = prior.confirmed_cv_volume_id
            return
        # prior 'proposed': the carried proposal (if any) stands; a proposal-
        # less prior (deferred / errored search) stays unanswered and falls
        # through to needs_proposal on this run.
        draft.state = "proposed"
        return
    # Brand-new group with no prior answer.
    if draft.parsed_count == 0:
        draft.state = "no_match"
        draft.message = (
            "files could not be parsed into a series; "
            "set the comicvine match manually"
        )


async def _propose_matches(
    settings: Settings | None,
    drafts: list[_GroupDraft],
    factory: HttpClientFactory | None,
    *,
    persist: Callable[[_GroupDraft], Awaitable[None]],
) -> None:
    """Attach at most one plausible ComicVine proposal per draft (in order),
    landing each outcome via ``persist`` as it resolves (progressive staging).

    Never auto-picks for the user — it annotates. Failures are recorded on the
    draft's visible message, never silently dropped; an auth rejection is
    reported with the static wording (no key material) and aborts the remaining
    searches, leaving those groups reviewable/overridable. A failed search
    never clears an existing proposal (only a successful search writes one).
    """
    if not drafts:
        return
    if settings is None:
        for draft in drafts:
            draft.message = "comicvine is not configured; set the match manually"
            await persist(draft)
        return
    floor = settings.library_import_similarity_floor
    factory = factory or comicvine_factory(settings)
    auth_failed = False
    async with ComicVineClient(settings, factory) as cv:
        for draft in drafts:
            if auth_failed:
                draft.message = _AUTH_FAILED_MESSAGE
                await persist(draft)
                continue
            term = draft.term or draft.matching_key
            try:
                result = await cv.search_series(term)
            except ComicVineAuthError:
                auth_failed = True
                draft.message = _AUTH_FAILED_MESSAGE
                logger.warning(
                    "library-import scan: comicvine auth rejected; "
                    "remaining match proposals skipped"
                )
                await persist(draft)
                continue
            except ComicVineError as exc:
                draft.message = f"comicvine search failed: {exc}"
                logger.warning(
                    "library-import scan: search for %r failed: %s", term, exc
                )
                await persist(draft)
                continue
            best = max(
                result.candidates,
                key=lambda c: c.plausibility.name_similarity,
                default=None,
            )
            if (
                best is not None
                and best.plausibility.name_similarity >= floor
            ):
                draft.proposed_cv_volume_id = best.series.cv_volume_id
                draft.proposal_name = best.series.name
                draft.proposal_start_year = best.series.start_year
                draft.proposal_publisher = best.series.publisher
                draft.proposal_image_url = best.series.image_url
                draft.message = None
            elif not result.complete:
                # A degraded/partial walk (mid-search outage) with no plausible
                # hit is NOT an answer: the group stays unanswered ``proposed``
                # so the next scan retries it, rather than pinning a no_match
                # verdict a healthy ComicVine might contradict.
                draft.message = (
                    f"comicvine search for {term!r} was incomplete; "
                    "re-run the scan or set the match manually"
                )
            else:
                draft.state = "no_match"
                if best is None:
                    draft.message = f"no comicvine results for {term!r}"
                else:
                    draft.message = (
                        f"no plausible comicvine match for {term!r} "
                        f"(best similarity "
                        f"{best.plausibility.name_similarity:.2f} below "
                        f"{floor})"
                    )
            await persist(draft)


async def _persist_proposal(
    db: Database, root_folder_id: int, draft: _GroupDraft
) -> None:
    """Land one draft's proposal outcome on its staged row (short write txn).

    Guarded so a user decision or an execute made DURING the proposal phase
    always wins: the update only applies while the row still exists as an
    undecided ``proposed`` group with no confirmed volume — a mid-scan PATCH
    (confirm/override/skip) or import is never reverted by the scan.
    """
    async with db.write_session() as session:
        row = (
            (
                await session.execute(
                    select(LibraryImportGroupRow).where(
                        LibraryImportGroupRow.root_folder_id == root_folder_id,
                        LibraryImportGroupRow.matching_key == draft.matching_key,
                    )
                )
            )
            .scalars()
            .first()
        )
        if row is None:
            return  # raced a re-scan; that scan owns the row now
        if row.state != "proposed" or row.confirmed_cv_volume_id is not None:
            return  # the user (or an execute) decided meanwhile — they win
        row.proposed_cv_volume_id = draft.proposed_cv_volume_id
        row.proposal_name = draft.proposal_name
        row.proposal_start_year = draft.proposal_start_year
        row.proposal_publisher = draft.proposal_publisher
        row.proposal_image_url = draft.proposal_image_url
        row.state = draft.state
        row.message = draft.message


async def _fail_if_execute_pending(session, root_folder_id: int) -> None:
    """Fail the scan fast when a ``library-import`` execute for this root is
    queued or running: the scan's delete+reinsert would invalidate the group
    ids that execute holds (scan-vs-execute race). The reverse direction needs
    no guard here — an execute enqueued after the scan's replace only ever
    sees the new rows, and the scan's later per-group proposal updates are
    guarded to never touch a decided/imported row."""
    rows = (
        (
            await session.execute(
                select(CommandRow).where(
                    CommandRow.name == "library-import",
                    CommandRow.status.in_(("queued", "started")),
                )
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        try:
            payload = json.loads(row.payload)
            group_ids = list(payload.get("group_ids") or [])
        except (json.JSONDecodeError, AttributeError):
            continue
        if not group_ids:
            continue
        hit = await session.scalar(
            select(LibraryImportGroupRow.id)
            .where(
                LibraryImportGroupRow.id.in_(group_ids),
                LibraryImportGroupRow.root_folder_id == root_folder_id,
            )
            .limit(1)
        )
        if hit is not None:
            raise LibraryImportScanBlockedError(
                f"a library-import execute (command {row.id}, {row.status}) "
                f"still holds staged groups of root folder {root_folder_id}; "
                "a re-scan now would invalidate its selection — wait for it "
                "to finish, then scan again"
            )


async def scan_library_root(
    db: Database,
    settings: Settings | None,
    root_folder_id: int,
    *,
    offload: OffloadFn | None = None,
    factory: HttpClientFactory | None = None,
    now: dt.datetime | None = None,
) -> str:
    """Scan one root folder into staging groups (FRG-IMP-022, FRG-IMP-023).

    Walk (junk-aware, bounded) → reconcile vanished rows → parse + group
    unmapped files by ``matching_key`` → REPLACE the root's staging rows in one
    write transaction (re-reading prior decisions and tracked files inside it:
    carry-forward + already-imported filtering happen at replace time) → then
    propose capped ComicVine matches, landing each on its row as it resolves
    (progressive staging — the review renders long before proposals finish).
    A missing root folder (deleted between enqueue and run) yields a skip
    summary rather than an error; a queued/running execute for this root fails
    the scan fast (:class:`LibraryImportScanBlockedError`). ``offload`` runs
    the FS-heavy walk and existence sweep off the event loop.
    """
    now = now or utcnow()
    async with db.read_session() as session:
        root = await session.get(RootFolderRow, root_folder_id)
        if root is None:
            logger.info(
                "library-import scan: root folder %d gone; skipped", root_folder_id
            )
            return f"root folder {root_folder_id} no longer exists; scan skipped"
        root_path = root.path
        await _fail_if_execute_pending(session, root_folder_id)
        # Rows to reconcile against disk (this root's series' files), plus a
        # tracked-path snapshot for the parse loop (re-read authoritatively
        # inside the replace transaction below).
        existing = await reconcile.issue_file_paths_for_root(session, root_folder_id)
        tracked = set(
            (await session.execute(select(IssueFileRow.path))).scalars().all()
        )

    # 1. Vanished-file reconciliation BEFORE staging (FRG-IMP-022): a stale DB
    #    record never blocks re-import of a replacement file.
    vanished_ids = (
        await offload(reconcile.vanished_file_ids, existing)
        if offload is not None
        else reconcile.vanished_file_ids(existing)
    )
    if vanished_ids:
        async with db.write_session() as session:
            await reconcile.remove_issue_files(session, vanished_ids)
        tracked -= {path for fid, path in existing if fid in set(vanished_ids)}

    # 2. Junk-aware bounded walk (shared with every other intake).
    def _walk() -> list[tuple[str, int]]:
        return matching.iter_archive_files(
            root_path, ARCHIVE_EXTENSIONS, max_depth=DEFAULT_MAX_WALK_DEPTH
        )

    files = await offload(_walk) if offload is not None else _walk()

    # 3. Parse + group the unmapped files.
    groups: dict[str, _GroupDraft] = {}
    unmapped = 0
    for path, size in files:
        if path in tracked:
            continue  # already imported — never duplicated (re-check semantics)
        unmapped += 1
        _draft_for_file(groups, path, size, now.year)

    cap = (
        settings.library_import_proposal_cap
        if settings is not None
        else LIBRARY_IMPORT_PROPOSAL_CAP
    )

    # 4. Atomically replace this root's staging rows — BEFORE the (potentially
    #    minutes-long) proposal phase. Prior decisions and the tracked-file set
    #    are re-read INSIDE this transaction, so a PATCH made or a file
    #    imported since the scan started is honored, never reverted/re-staged.
    async with db.write_session() as session:
        tracked_now = set(
            (await session.execute(select(IssueFileRow.path))).scalars().all()
        )
        prior_rows = {
            row.matching_key: row
            for row in (
                await session.execute(
                    select(LibraryImportGroupRow).where(
                        LibraryImportGroupRow.root_folder_id == root_folder_id
                    )
                )
            ).scalars()
        }
        kept: dict[str, _GroupDraft] = {}
        for key, draft in groups.items():
            draft.files = [
                (path, size) for path, size in draft.files if path not in tracked_now
            ]
            if not draft.files:
                continue  # every file got imported mid-scan — nothing to stage
            _carry_forward(draft, prior_rows.get(key))
            kept[key] = draft

        # Proposal budget: biggest groups first, only unanswered ones.
        to_propose = [
            draft
            for _key, draft in sorted(
                kept.items(), key=lambda kv: (-len(kv[1].files), kv[0])
            )
            if draft.needs_proposal
        ]
        over_cap = to_propose[cap:]
        if over_cap:
            logger.warning(
                "library-import scan: %d group(s) beyond the %d-proposal cap; "
                "staged without a proposed match (re-scan later or match "
                "manually)",
                len(over_cap),
                cap,
            )
            for draft in over_cap:
                draft.message = (
                    f"match proposal deferred (scan proposes at most "
                    f"{cap} groups per run); "
                    "re-run the scan or set the match manually"
                )
        to_propose = to_propose[:cap]
        for draft in to_propose:
            draft.message = "comicvine match proposal pending"

        await session.execute(
            delete(LibraryImportGroupRow).where(
                LibraryImportGroupRow.root_folder_id == root_folder_id
            )
        )
        for draft in kept.values():
            session.add(
                LibraryImportGroupRow(
                    matching_key=draft.matching_key,
                    root_folder_id=root_folder_id,
                    folder=draft.folder,
                    files=encode_group_files(draft.files),
                    confidence=draft.confidence,
                    proposed_cv_volume_id=draft.proposed_cv_volume_id,
                    confirmed_cv_volume_id=draft.confirmed_cv_volume_id,
                    proposal_name=draft.proposal_name,
                    proposal_start_year=draft.proposal_start_year,
                    proposal_publisher=draft.proposal_publisher,
                    proposal_image_url=draft.proposal_image_url,
                    state=draft.state,
                    message=draft.message,
                    scanned_at=now,
                )
            )

    # 5. Proposal phase: each outcome lands on its row as it resolves.
    async def _persist(draft: _GroupDraft) -> None:
        await _persist_proposal(db, root_folder_id, draft)

    await _propose_matches(settings, to_propose, factory, persist=_persist)

    states = [d.state for d in kept.values()]
    summary = (
        f"groups={len(kept)} "
        f"proposed={sum(1 for s in states if s == 'proposed')} "
        f"confirmed={sum(1 for s in states if s == 'confirmed')} "
        f"no_match={sum(1 for s in states if s == 'no_match')} "
        f"skipped={sum(1 for s in states if s == 'skipped')} "
        f"unmapped_files={unmapped} vanished_removed={len(vanished_ids)}"
    )
    logger.info("library-import scan root %d: %s", root_folder_id, summary)
    return summary


# --- execute -------------------------------------------------------------------


def importable_volume(group: LibraryImportGroupRow) -> int | None:
    """The ComicVine volume this group would import, or ``None`` when it is not
    importable. Selection IS confirmation: a ``confirmed`` group imports its
    confirmed volume; a ``proposed`` group WITH an attached proposal imports
    the proposal (auto-confirming at execute). ``no_match``/``skipped``/
    ``imported`` groups and proposal-less ``proposed`` groups are never
    importable. Shared by the API's up-front validation and the flow."""
    if group.state == "confirmed" and group.confirmed_cv_volume_id is not None:
        return group.confirmed_cv_volume_id
    if group.state == "proposed" and group.proposed_cv_volume_id is not None:
        return group.proposed_cv_volume_id
    return None


def _shorten(reasons: list[str], *, limit: int = 3, width: int = 400) -> str:
    """A bounded, human-visible tail of blocked reasons for the group message."""
    shown = "; ".join(reasons[:limit])
    if len(reasons) > limit:
        shown += f"; (+{len(reasons) - limit} more)"
    return shown[:width]


async def _set_group_outcome(
    db: Database,
    group_id: int,
    *,
    state: str | None,
    message: str | None,
    rejections: list[str] | None = None,
) -> None:
    """Annotate the staging row with an execute outcome. ``rejections`` (when
    given) replaces the structured per-file blocked-reason list; ``None``
    leaves the stored list untouched (pre-import failures keep the last
    attempt's reasons)."""
    async with db.write_session() as session:
        group = await session.get(LibraryImportGroupRow, group_id)
        if group is None:  # raced a re-scan; nothing to annotate
            return
        if state is not None:
            group.state = state
        group.message = message
        if rejections is not None:
            group.rejections = encode_rejections(rejections)


async def _series_for_volume(db: Database, cv_volume_id: int) -> SeriesRow | None:
    async with db.read_session() as session:
        return (
            (
                await session.execute(
                    select(SeriesRow).where(SeriesRow.cv_volume_id == cv_volume_id)
                )
            )
            .scalars()
            .first()
        )


async def _issue_count(db: Database, series_id: int) -> int:
    async with db.read_session() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(IssueRow)
            .where(IssueRow.series_id == series_id)
        )
    return int(count or 0)


async def _refresh_before_import(
    db: Database,
    settings: Settings | None,
    commands: CommandService,
    group_id: int,
    series_id: int,
    factory: HttpClientFactory | None,
) -> bool:
    """Populate the series' issue list deterministically before importing
    (files can only match issues that exist). Returns False — with the failure
    visible on the staging row — when the refresh could not run."""
    try:
        await refresh_series(db, settings, series_id, commands=commands, factory=factory)
    except ComicVineError as exc:
        message = (
            f"metadata refresh failed before import: {COMICVINE_CREDENTIAL_MESSAGE}"
            if isinstance(exc, ComicVineAuthError)
            else f"metadata refresh failed before import: {exc}"
        )
        await _set_group_outcome(db, group_id, state=None, message=message)
        return False
    return True


async def _import_group(
    db: Database,
    settings: Settings | None,
    commands: CommandService,
    group: LibraryImportGroupRow,
    *,
    format_profile_id: int | None,
    monitor_strategy: str,
    search_on_add: bool,
    offload: OffloadFn | None,
    factory: HttpClientFactory | None,
    now: dt.datetime,
) -> str:
    """Import one confirmed group; returns its one-word outcome for the summary.

    The staging row is annotated (state + message + structured rejections)
    with whatever happened — imported, partially blocked (reasons visible), a
    safety-rail block, or add/refresh failure — so no outcome is ever silent
    (FRG-IMP-023).
    """
    assert group.confirmed_cv_volume_id is not None
    in_place = (
        getattr(settings, "library_import_mode", "in_place") if settings else "in_place"
    ) != "move"

    # Safety rail: a group whose folder IS the root folder (loose files at the
    # root, groups spanning sibling folders) must never become a series whose
    # path is the root — a later per-series rescan would swallow the whole
    # library. In move mode the normal per-series path is built instead.
    if in_place and group.folder:
        async with db.read_session() as session:
            root = await session.get(RootFolderRow, group.root_folder_id)
        if root is not None and os.path.realpath(group.folder) == os.path.realpath(
            root.path
        ):
            await _set_group_outcome(
                db,
                group.id,
                state=None,
                message=(
                    "group has no dedicated folder; move the files into one "
                    "or import with move mode"
                ),
            )
            return "no-folder"

    # Series: reuse an existing row for the volume ONLY when that is provably
    # the in-place re-run case (same on-disk folder — e.g. finishing a partial
    # import); otherwise the volume already lives elsewhere in the library and
    # importing would move/register this group's files at a foreign series —
    # block visibly, files left untouched. No existing series: create it
    # through the ONE add flow (CV fetch, path build; refresh handled below —
    # enqueue_refresh=False so the group gets EXACTLY one refresh).
    series = await _series_for_volume(db, group.confirmed_cv_volume_id)
    if series is not None:
        same_folder = bool(group.folder) and os.path.realpath(
            series.path
        ) == os.path.realpath(group.folder)
        if not (in_place and same_folder):
            await _set_group_outcome(
                db,
                group.id,
                state=None,
                message=(
                    f"volume already in library at {series.path}; "
                    "files left untouched"
                ),
            )
            return "duplicate"
    else:
        try:
            result = await add_series(
                db,
                settings,
                cv_volume_id=group.confirmed_cv_volume_id,
                root_folder_id=group.root_folder_id,
                commands=commands,
                format_profile_id=format_profile_id,
                monitor_strategy=monitor_strategy,
                search_on_add=search_on_add,
                path_override=group.folder if in_place else None,
                enqueue_refresh=False,
                factory=factory,
            )
        except SeriesValidationError as exc:
            await _set_group_outcome(
                db, group.id, state=None, message=f"add failed: {exc}"
            )
            return "add-failed"
        series = result.series

    # Populate the issue list DETERMINISTICALLY before importing: files can
    # only match issues that exist. Runs for a just-created series (always
    # issueless) and for a reused series whose add-enqueued refresh is still
    # pending — never for a series that already has its issues (no double
    # fetch/scan).
    if await _issue_count(db, series.id) == 0:
        if not await _refresh_before_import(
            db, settings, commands, group.id, series.id, factory
        ):
            return "refresh-failed"

    ctx = ImportContext(
        library_root=series.path,
        config_dir=str(settings.config_dir) if settings is not None else ".",
        reference_year=series.start_year or now.year,
        now=now,
        offload=offload,
        **media_management_fields(settings),
    )
    source = LibraryImportSource(
        series_id=series.id,
        files=tuple(path for path, _size in decode_group_files(group.files)),
        container_root=group.folder or None,
    )

    imported = 0
    blocked_reasons: list[str] = []
    async with db.write_session() as session:
        candidates = await gather(source, session, ctx)
        for candidate in candidates:
            outcome = await import_candidate(session, candidate, ctx)
            if outcome.status is ImportStatus.IMPORTED:
                imported += 1
            else:
                blocked_reasons.append(
                    f"{candidate.file_name}: "
                    + "; ".join(outcome.reasons or ("blocked",))
                )

    if not candidates:
        await _set_group_outcome(
            db,
            group.id,
            state=None,
            message="no staged files remain on disk; re-run the scan",
            rejections=[],
        )
        return "empty"
    if blocked_reasons:
        await _set_group_outcome(
            db,
            group.id,
            state=None,  # stays confirmed → re-runnable after the user fixes it
            message=(
                f"imported={imported} blocked={len(blocked_reasons)}: "
                + _shorten(blocked_reasons)
            ),
            rejections=blocked_reasons,
        )
        return "partial" if imported else "blocked"
    await _set_group_outcome(
        db,
        group.id,
        state="imported",
        message=f"imported={imported}",
        rejections=[],
    )
    return "imported"


async def execute_library_import(
    db: Database,
    settings: Settings | None,
    group_ids: list[int],
    *,
    commands: CommandService,
    format_profile_id: int | None = None,
    monitor_strategy: str = "all",
    search_on_add: bool = False,
    offload: OffloadFn | None = None,
    factory: HttpClientFactory | None = None,
    now: dt.datetime | None = None,
) -> str:
    """Bulk-import the selected groups (FRG-IMP-023).

    Selection IS confirmation: a ``proposed`` group with an attached proposal
    is promoted to ``confirmed`` (adopting the proposal as its confirmed
    volume) before importing. Groups are processed independently: one group's
    failure (a ComicVine error, a validation rejection, blocked files) is
    recorded on ITS staging row and never abandons the rest of the batch.
    Non-importable/unknown ids are counted and skipped — the API validates up
    front, but the queue payload may be stale by run time (a re-scan replaced
    the rows).
    """
    now = now or utcnow()
    tallies: dict[str, int] = {}
    for group_id in group_ids:
        # Read + (when applicable) auto-confirm promotion in ONE write txn so
        # the check-and-promote can't race a concurrent PATCH.
        async with db.write_session() as session:
            group = await session.get(LibraryImportGroupRow, group_id)
            if group is not None:
                if (
                    group.state == "proposed"
                    and group.proposed_cv_volume_id is not None
                ):
                    group.state = "confirmed"
                    group.confirmed_cv_volume_id = group.proposed_cv_volume_id
                await session.flush()
                session.expunge(group)
        if group is None:
            outcome = "missing"
        elif group.state != "confirmed" or group.confirmed_cv_volume_id is None:
            outcome = "not-confirmed"
        else:
            try:
                outcome = await _import_group(
                    db,
                    settings,
                    commands,
                    group,
                    format_profile_id=format_profile_id,
                    monitor_strategy=monitor_strategy,
                    search_on_add=search_on_add,
                    offload=offload,
                    factory=factory,
                    now=now,
                )
            except Exception as exc:  # noqa: BLE001 — isolate groups (like the drain)
                logger.exception(
                    "library-import: group %d failed unexpectedly", group_id
                )
                await _set_group_outcome(
                    db, group_id, state=None, message=f"import failed: {exc}"
                )
                outcome = "errored"
        tallies[outcome] = tallies.get(outcome, 0) + 1

    summary = " ".join(f"{key}={count}" for key, count in sorted(tallies.items()))
    logger.info("library-import: %s", summary or "no groups selected")
    return summary or "no groups selected"


# --- command handlers -----------------------------------------------------------


@register_handler("library-import-scan")
async def _handle_scan(
    command: LibraryImportScanCommand, ctx: HandlerContext
) -> str:
    return await scan_library_root(
        ctx.db, ctx.settings, command.root_folder_id, offload=ctx.offload
    )


@register_handler("library-import")
async def _handle_execute(command: LibraryImportCommand, ctx: HandlerContext) -> str:
    commands = ctx.commands or CommandService(ctx.db, ctx.settings)
    return await execute_library_import(
        ctx.db,
        ctx.settings,
        command.group_ids,
        commands=commands,
        format_profile_id=command.format_profile_id,
        monitor_strategy=command.monitor_strategy,
        search_on_add=command.search_on_add,
        offload=ctx.offload,
    )


__all__ = [
    "LIBRARY_IMPORT_PROPOSAL_CAP",
    "LIBRARY_IMPORT_SIMILARITY_FLOOR",
    "LibraryImportCommand",
    "LibraryImportScanBlockedError",
    "LibraryImportScanCommand",
    "decode_group_files",
    "decode_rejections",
    "encode_group_files",
    "encode_rejections",
    "execute_library_import",
    "importable_volume",
    "scan_library_root",
]
