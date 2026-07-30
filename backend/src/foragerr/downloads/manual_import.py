"""Manual-import listing + execution (FRG-PP-016, FRG-API-015).

The resolution path the M1 ``import_blocked`` state points at. It drives the SAME
shared import pipeline as automatic import — ``gather → aggregate →
build_evaluation → decide (→ execute)`` — with a :class:`ManualImportSource`
producing neutral candidates and per-file :class:`ManualOverride`s entering as the
top-priority reconciliation layer. There is no separate manual code path and no
"force": the FULL ``default_specs()`` set runs over every candidate, so an
override can supply the series/issue mapping but never bypass the archive-valid /
junk / free-space / already-imported / upgrade safety specs.

Two halves:

- :func:`list_manual_candidates` — read-only. Lists a folder (or a blocked
  download's files) with each file's would-be decision, rejection reasons,
  suggested mapping, and embedded-metadata summary. Touches no disk beyond
  inspection.
- :class:`ManualImportCommand` / :func:`execute_manual_import` — the pp-pool
  command (same exclusivity group as ``rename-series``) that imports the picked
  files under their overrides through ``import_candidate``, recording history
  exactly as automatic import. Blocked/failed files stay available for another
  attempt.

Path safety (FRG-SEC-004): every filesystem path a caller supplies is confined to
a managed root — a registered library root folder, or a tracked download's own
output path — via :func:`foragerr.security.paths.validate_under_root`, so neither
the listing nor the command can be steered at an arbitrary path.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
from dataclasses import dataclass
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from foragerr.commands.registry import BaseCommand, register_command, register_handler
from foragerr.commands.service import HandlerContext
from foragerr.config import Settings
from foragerr.db import Database, utcnow
from foragerr.downloads.imports import (
    _withdraw_import,
    build_import_context,
    finalize_download_import,
    run_post_import_side_effects,
)
from foragerr.downloads.models import TrackedDownloadRow
from foragerr.downloads.repo import load_mappings
from foragerr.downloads.state import TrackedDownloadState
from foragerr.importer import (
    IMPORT_FILE_MUTATION_GROUP,
    CompletedDownloadSource,
    ImportCandidate,
    ImportOutcome,
    ImportStatus,
    ManualImportSource,
    ManualOverride,
    import_candidate,
)
from foragerr.importer.decisions import decide
from foragerr.importer.pipeline import aggregate_candidate, build_evaluation, gather
from foragerr.library import repo
from foragerr.security.paths import PathConfinementError, validate_under_root
from foragerr.sources.import_hook import source_import_withdrawn

logger = logging.getLogger("foragerr.downloads.manual_import")


class ManualImportError(Exception):
    """A bad manual-import request (unreadable path / unknown download).

    Carries the HTTP status the API surfaces as a typed :class:`ApiError`."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


#: Hard cap on the number of candidate files one listing inspects+reports. A
#: manual-import listing inspects EVERY file (archive I/O per file), so an
#: enormous folder must not fan out unboundedly (DoS). Beyond the cap the list is
#: truncated and flagged; the operator narrows the folder (FRG-API-015).
MANUAL_IMPORT_LISTING_CAP = 500


@dataclass(frozen=True, slots=True)
class ManualEntry:
    """One candidate's would-be verdict for the listing (FRG-API-015)."""

    candidate: ImportCandidate
    approved: bool
    rejections: tuple[str, ...]
    suggested_series_id: int | None
    suggested_issue_id: int | None
    format: str | None
    comic_info_present: bool
    embedded_cv_issue_id: int | None
    embedded_verified: bool


@dataclass(frozen=True, slots=True)
class ManualListing:
    """A manual-import listing result (FRG-API-015): the (possibly capped) entries
    plus a ``truncated`` flag the API surfaces when the folder exceeded the cap."""

    entries: tuple[ManualEntry, ...]
    truncated: bool = False


class ManualFileSpec(BaseModel):
    """One picked file's corrected mapping in a manual-import execute request."""

    model_config = ConfigDict(extra="forbid")

    path: str
    series_id: int | None = None
    issue_id: int | None = None
    format: str | None = None
    #: When the listing came from a blocked download, the id that download is
    #: tracked under (FRG-PP-016). Carried so execute rebuilds the file through
    #: the SAME download-shaped source — grab hints + remote-path mapping +
    #: download_id — and every spec (especially ``AlreadyImportedSpec``) evaluates
    #: exactly as the listing did. ``None`` for arbitrary-folder / file picks.
    download_id: str | None = None


@register_command
class ManualImportCommand(BaseCommand):
    """Import operator-picked files under their overrides (FRG-PP-016).

    Runs on the ``pp`` pool inside the importer's file-mutation exclusivity group
    — the same transport ``rename-series`` uses — so a manual import never mutates
    the library concurrently with a drain, rescan, or rename."""

    name: Literal["manual-import"] = "manual-import"
    workload_class: ClassVar[str] = "pp"
    exclusivity_group: ClassVar[str | None] = IMPORT_FILE_MUTATION_GROUP
    files: list[ManualFileSpec]


# --- allowed-root confinement ------------------------------------------------


async def _library_roots(db: Database) -> list[str]:
    async with db.read_session() as session:
        return [row.path for row in await repo.list_root_folders(session)]


async def _read_only_roots(db: Database) -> list[str]:
    """The read-only reference roots a manual import may never draw FROM
    (FRG-SER-021).

    Confinement asks whether a picked file is under a managed root; a read-only
    root IS one, so without this a reference library reads as a legitimate
    manual-import source and its files get moved out of it into a managed
    series. Empty for an installation with no read-only root."""
    async with db.read_session() as session:
        return await repo.read_only_root_paths(session)


def _under_read_only_root(raw_path: str, read_only_roots: list[str]) -> bool:
    """Whether ``raw_path`` resolves at or under one of ``read_only_roots``."""
    if not read_only_roots:
        return False
    try:
        validate_under_root(raw_path, read_only_roots)
    except (PathConfinementError, OSError):
        return False
    return True


async def execute_roots(db: Database) -> list[str]:
    """Roots a manual-import execute may draw files from: registered library root
    folders plus every tracked download's own output path (so a blocked
    download's staged files are importable). Public helper the API shares
    (FRG-API-015)."""
    async with db.read_session() as session:
        roots = [row.path for row in await repo.list_root_folders(session)]
        outputs = (
            (
                await session.execute(
                    select(TrackedDownloadRow.output_path).where(
                        TrackedDownloadRow.output_path.is_not(None)
                    )
                )
            )
            .scalars()
            .all()
        )
    return roots + [out for out in outputs if out]


def confine_under_roots(raw_path: str, roots: list[str]) -> str | None:
    """The realpath of ``raw_path`` when it is under one of ``roots`` AND exists;
    else ``None``. The single sanctioned containment check (FRG-SEC-004).

    Confinement is checked FIRST (resolve + :func:`validate_under_root`), and only
    a confined path is then stat'd. A path OUTSIDE every root returns ``None``
    regardless of whether it exists, so a caller cannot distinguish "outside root,
    exists" from "outside root, absent" — there is no filesystem-existence oracle
    for arbitrary paths (and a resolved path outside the roots is never echoed
    back). ``validate_under_root`` resolves without requiring existence, so the
    order is safe."""
    try:
        resolved = validate_under_root(raw_path, roots)
    except PathConfinementError:
        return None
    if not os.path.exists(resolved):
        return None
    return str(resolved)


# --- read-only listing (GET) -------------------------------------------------


async def _completed_source_for_download(
    db: Database, download_id: str
) -> tuple[CompletedDownloadSource, int]:
    """Rebuild the :class:`CompletedDownloadSource` for a tracked download id.

    The single place the download-shaped source is assembled (latest tracked row,
    its remote-path mappings, output path, grab-record join), so the listing and
    the execute path share IDENTICAL download context (FRG-PP-016). Returns the
    source together with that tracked row's id, which the execute path needs to
    apply the terminal state to the SAME row it drew the files from. Raises a
    typed 404 when no such download is tracked."""
    async with db.read_session() as session:
        row = (
            (
                await session.execute(
                    select(TrackedDownloadRow)
                    .where(TrackedDownloadRow.download_id == download_id)
                    .order_by(TrackedDownloadRow.id.desc())
                )
            )
            .scalars()
            .first()
        )
    if row is None:
        raise ManualImportError(404, f"no tracked download with id {download_id!r}")
    mappings = (
        await load_mappings(db, row.client_id) if row.client_id is not None else []
    )
    return (
        CompletedDownloadSource(
            download_id=row.download_id,
            output_path=row.output_path or "",
            client_id=row.client_id,
            client_title=row.title,
            mappings=tuple(mappings),
        ),
        row.id,
    )


async def _build_read_source(
    db: Database,
    ctx,
    *,
    path: str | None,
    download_id: str | None,
) -> ManualImportSource:
    if download_id is not None:
        completed, _row_id = await _completed_source_for_download(db, download_id)
        return ManualImportSource(download=completed)

    assert path is not None
    # Confine FIRST, then the source walks the confined folder. A path outside the
    # managed roots yields a SINGLE generic error whether or not it exists (no
    # existence oracle, no echoed out-of-root path) — FRG-SEC-004 / FRG-API-015.
    confined = confine_under_roots(path, await _library_roots(db))
    if confined is None:
        raise ManualImportError(400, "path is not under a managed library root")
    if _under_read_only_root(confined, await _read_only_roots(db)):
        # Refused at the LISTING, not only at execute: offering a reference
        # library's files as import candidates is what makes moving them out of
        # it ordinary UI use (FRG-SER-021).
        raise ManualImportError(
            409,
            "path is inside a read-only reference library (browse and serve "
            "only); it cannot be a manual-import source",
        )
    return ManualImportSource(folder_path=confined)


async def list_manual_candidates(
    db: Database,
    settings: Settings | None,
    *,
    path: str | None = None,
    download_id: str | None = None,
    offload=None,
    now: dt.datetime | None = None,
) -> ManualListing:
    """List candidate files with their would-be decisions (FRG-API-015).

    Exactly one of ``path`` / ``download_id`` must be given. Read-only: runs
    ``gather → aggregate → build_evaluation → decide`` per candidate, touching no
    disk beyond archive inspection.

    Two DoS guards: the candidate list is capped at
    :data:`MANUAL_IMPORT_LISTING_CAP` (an over-cap folder returns the capped list
    with ``truncated=True`` rather than fanning out unboundedly), and the
    per-candidate archive inspection is pushed off the event loop through
    ``offload`` (the caller passes ``daemon_offload``, matching execute) so a big
    listing never blocks the shared loop.
    """
    if (path is None) == (download_id is None):
        raise ManualImportError(
            400, "exactly one of path or downloadId must be supplied"
        )
    now = now or utcnow()
    ctx = await build_import_context(db, settings, now=now, offload=offload)
    source = await _build_read_source(db, ctx, path=path, download_id=download_id)

    entries: list[ManualEntry] = []
    truncated = False
    async with db.read_session() as session:
        candidates = await gather(source, session, ctx)
        if len(candidates) > MANUAL_IMPORT_LISTING_CAP:
            logger.warning(
                "manual-import: listing for %s truncated at %d of %d candidates",
                path or f"download {download_id!r}",
                MANUAL_IMPORT_LISTING_CAP,
                len(candidates),
            )
            candidates = candidates[:MANUAL_IMPORT_LISTING_CAP]
            truncated = True
        for candidate in candidates:
            evidence = aggregate_candidate(candidate, ctx)
            ev = await build_evaluation(session, candidate, evidence, ctx)
            decision = decide(ev)
            entries.append(
                ManualEntry(
                    candidate=candidate,
                    approved=decision.approved,
                    rejections=decision.reasons,
                    suggested_series_id=decision.series_id,
                    suggested_issue_id=decision.issue_id,
                    format=ev.new_format,
                    comic_info_present=ev.comic_info_present,
                    embedded_cv_issue_id=ev.embedded_cv_issue_id,
                    embedded_verified=ev.embedded_verified,
                )
            )
    return ManualListing(entries=tuple(entries), truncated=truncated)


# --- execution (POST command) ------------------------------------------------


def _override_for(spec: ManualFileSpec) -> ManualOverride:
    return ManualOverride(
        series_id=spec.series_id, issue_id=spec.issue_id, format=spec.format
    )


#: The reason carried by a file the operator simply left out of this pick — it
#: would evaluate clean, so nothing is wrong with it beyond still being unresolved.
UNPICKED_REASON = "not selected in this manual import"


async def _unpicked_outcome(session, candidate: ImportCandidate, ctx) -> ImportOutcome:
    """A gathered-but-unpicked file's contribution to its download's verdict.

    A download-scoped pick resolves a SUBSET of a blocked download's files, but
    the tracked row's verdict is folded over the whole download: importing one of
    two files must not fold to ``imported`` and wipe the other file's reasons off
    the queue (FRG-PP-016). So every file this plan gathered but did not import
    contributes a synthesized BLOCKED outcome.

    The reason is re-derived through the SAME ``aggregate → evaluate → decide``
    read path the listing uses, so what the tracked row reports is what the
    operator sees in the manual-import UI — never invented text.

    Files imported on an EARLIER pass were moved out of the download's staging
    path, so they are no longer gathered at all; the fold therefore converges to
    ``imported`` once every file is genuinely resolved. BLOCKED (never FAILED) so
    an untouched file can never route the whole download into the failure loop.
    """
    evidence = aggregate_candidate(candidate, ctx)
    ev = await build_evaluation(session, candidate, evidence, ctx)
    decision = decide(ev)
    reasons = tuple(decision.reasons or ())
    if decision.approved or not reasons:
        reasons = (UNPICKED_REASON,)
    return ImportOutcome(
        status=ImportStatus.BLOCKED, candidate=candidate, reasons=reasons
    )


async def execute_manual_import(
    db: Database,
    settings: Settings | None,
    files: list[ManualFileSpec],
    *,
    commands=None,
    offload=None,
    now: dt.datetime | None = None,
) -> str:
    """Import the picked files under their overrides (FRG-PP-016).

    Each file becomes a ``SOURCE_MANUAL`` candidate carrying its override and runs
    the full shared pipeline. Returns an ``imported=N blocked=M failed=K`` summary.

    **Download-scoped files** (``spec.download_id`` set — the listing came from a
    blocked download) are rebuilt through the SAME download-shaped source the
    listing used: :func:`CompletedDownloadSource.gather` supplies the remote-path
    mapping, the grab-record hints, and the ``download_id`` so ``AlreadyImportedSpec``
    (and every other spec) evaluate IDENTICALLY to the listing — a file the
    listing showed as already-imported/blocked cannot slip through at execute by
    losing its download context. Confinement for these is the download's own file
    set: only a path the download actually produced is imported (a foreign path is
    dropped as unmatched).

    **Arbitrary-folder / file picks** (no ``download_id``) are re-confined to a
    managed root (defence in depth even though the API validated them at enqueue):
    a file outside every root is dropped rather than imported from an arbitrary
    location.

    A download-scoped group also ENDS like the automatic drain: its outcomes —
    the imported ones plus a synthesized BLOCKED outcome per gathered-but-unpicked
    file (:func:`_unpicked_outcome`) so a partial pick can never fold to
    ``imported`` — go through the drain's own
    :func:`~foragerr.downloads.imports.finalize_download_import`, so the tracked
    queue row leaves ``import_blocked`` (emitting the same queue event) and a
    store download's entitlement mirrors the verdict with FRG-SRC-007
    owned-via-edition reconciliation — in this same write transaction
    (FRG-PP-016, FRG-SRC-006). Once that transaction commits, the drain's
    post-commit half runs too
    (:func:`~foragerr.downloads.imports.run_post_import_side_effects`) — with the
    SAME ``commands`` handle the drain passes, so a manual failure promotion also
    enqueues the replacement issue-search (FRG-DL-013) instead of silently
    skipping it — and a client-backed download is removed/marked exactly as a
    drained one (FRG-DL-010). Arbitrary-folder picks touch no tracked row.

    A download-scoped plan also carries the drain's store-source WITHDRAWAL gate
    (FRG-SRC-004): the plan is built from a snapshot taken before its write
    transaction, so an operator ignore can commit in between — deleting the
    tracked row and clearing the entitlement's download axis. The gate is
    re-checked INSIDE the write transaction, before any file moves, so a
    withdrawn item imports nothing.

    Each plan (one download, or the whole arbitrary-folder pick) owns its OWN
    write session, as the drain gives each download: file moves are irreversible,
    so one plan's failure must never roll back another's committed rows.
    """
    now = now or utcnow()
    ctx = await build_import_context(db, settings, now=now, offload=offload)
    roots = await execute_roots(db)
    read_only_roots = await _read_only_roots(db)

    # Partition: download-scoped specs group by their download id; the rest are
    # plain path picks.
    by_download: dict[str, list[ManualFileSpec]] = {}
    plain: list[ManualFileSpec] = []
    for spec in files:
        if spec.download_id:
            by_download.setdefault(spec.download_id, []).append(spec)
        else:
            plain.append(spec)

    # A plan is a source, the set of local paths to keep (``None`` = keep all, for
    # the files-only source which gathers exactly its inputs), and the tracked
    # download to finalize afterwards as ``(download_id, row_id, client_id)``
    # (``None`` for arbitrary-folder picks, which own no queue row).
    plans: list[
        tuple[ManualImportSource, set[str] | None, tuple[str, int, int | None] | None]
    ] = []
    dropped = 0

    if plain:
        resolved: list[str] = []
        overrides: dict[str, ManualOverride] = {}
        for spec in plain:
            confined = confine_under_roots(spec.path, roots)
            if confined is None:
                dropped += 1
                logger.warning(
                    "manual-import: dropping file outside any managed root: %s",
                    spec.path,
                )
                continue
            if _under_read_only_root(confined, read_only_roots):
                # Defence in depth behind the endpoint's 409 and the pipeline's
                # own source-side refusal: a file inside a reference library is
                # never imported OUT of it, whatever destination the pick names
                # (FRG-SER-021).
                dropped += 1
                logger.warning(
                    "manual-import: dropping file inside a read-only reference "
                    "library: %s",
                    confined,
                )
                continue
            resolved.append(confined)
            overrides[confined] = _override_for(spec)
        if resolved:
            plans.append(
                (
                    ManualImportSource(files=tuple(resolved), overrides=overrides),
                    None,
                    None,
                )
            )

    for download_id, specs in by_download.items():
        try:
            completed, row_id = await _completed_source_for_download(db, download_id)
        except ManualImportError:
            dropped += len(specs)
            logger.warning(
                "manual-import: dropping %d file(s) for unknown download %r",
                len(specs),
                download_id,
            )
            continue
        overrides = {spec.path: _override_for(spec) for spec in specs}
        picked = {spec.path for spec in specs}
        plans.append(
            (
                ManualImportSource(download=completed, overrides=overrides),
                picked,
                (download_id, row_id, completed.client_id),
            )
        )

    imported = blocked = failed = unresolved = withdrawn = 0
    for source, picked, tracked in plans:
        # ONE write session PER PLAN, matching the drain's per-download isolation
        # (FRG-DL-009): ``import_candidate`` moves files on disk inside the
        # transaction, so a later plan raising must never roll back an earlier
        # plan's rows whose files have already moved — that would orphan them.
        final_state: TrackedDownloadState | None = None
        acted = False
        async with db.write_session() as session:
            if tracked is not None and await source_import_withdrawn(
                session, tracked[0]
            ):
                # The drain's store-source withdrawal gate (FRG-SRC-004), applied
                # to the manual path with the SAME in-transaction ordering. The
                # tracked row and its source were snapshotted BEFORE this write
                # transaction, so an ``ignore`` can have committed in between;
                # without this re-check the plan would still move the file into
                # the library and write issue_files while ``apply_source_import``
                # skipped the entitlement mirror — an operator-withdrawn store
                # item imported under withdrawn-looking state. Re-checked here,
                # before ANY file move, so a withdrawn plan imports nothing.
                #
                # Termination is the drain's own :func:`_withdraw_import`
                # (shared, never re-implemented): the tracked row is deleted so a
                # later restore + re-accept can hand off afresh — usually already
                # gone, since ``ignore_entitlement`` deletes any non-``importing``
                # row itself, in which case there is simply nothing to finalize.
                dl_id, row_id, _client_id = tracked
                await _withdraw_import(session, row_id, dl_id)
                withdrawn += 1
                continue
            outcomes: list[ImportOutcome] = []
            for candidate in await gather(source, session, ctx):
                if picked is not None and candidate.local_path not in picked:
                    # A download file the operator did not pick: not imported,
                    # but still part of this download's verdict — see
                    # :func:`_unpicked_outcome`.
                    outcomes.append(await _unpicked_outcome(session, candidate, ctx))
                    unresolved += 1
                    continue
                acted = True
                outcome = await import_candidate(session, candidate, ctx)
                outcomes.append(outcome)
                if outcome.status is ImportStatus.IMPORTED:
                    imported += 1
                elif outcome.status is ImportStatus.FAILED:
                    failed += 1
                else:
                    blocked += 1
            if tracked is not None and acted:
                # The drain's ending, on the drain's own aggregation policy: the
                # queue row leaves import_blocked with the same event, and a
                # store entitlement mirrors + reconciles (FRG-PP-016,
                # FRG-SRC-006/007). Skipped when nothing the operator picked
                # actually ran for this download (every picked path unmatched) —
                # an attempt that imported nothing must not rewrite the row's
                # state from thin air.
                dl_id, row_id, _client_id = tracked
                final_state = await finalize_download_import(
                    session,
                    row_id=row_id,
                    download_id=dl_id,
                    outcomes=outcomes,
                    now=ctx.now,
                )
        if tracked is not None and final_state is not None:
            # ...and the drain's post-COMMIT half too, so a client-backed download
            # resolved by hand still gets its remove / mark-imported and a failed
            # one still enters the failure loop (FRG-DL-010, FRG-PP-016). Outside
            # the write session: the writer lock is not re-entrant.
            dl_id, _row_id, client_id = tracked
            await run_post_import_side_effects(
                db,
                settings,
                final_state=final_state,
                client_id=client_id,
                download_id=dl_id,
                commands=commands,
                now=ctx.now,
            )

    summary = f"imported={imported} blocked={blocked} failed={failed}"
    if unresolved:
        summary += f" unresolved={unresolved}"
    if withdrawn:
        summary += f" withdrawn={withdrawn}"
    if dropped:
        summary += f" dropped={dropped}"
    logger.info("manual-import: %s", summary)
    return summary


@register_handler("manual-import")
async def _handle_manual_import(
    command: ManualImportCommand, ctx: HandlerContext
) -> str:
    # ``ctx.commands`` is threaded through exactly as ProcessImportsCommand does
    # (FRG-DL-013): the post-commit half enqueues the replacement issue-search on
    # a failure promotion, which needs the command service handle.
    return await execute_manual_import(
        ctx.db,
        ctx.settings,
        command.files,
        commands=ctx.commands,
        offload=ctx.offload,
    )


__all__ = [
    "MANUAL_IMPORT_LISTING_CAP",
    "ManualEntry",
    "ManualFileSpec",
    "ManualImportCommand",
    "ManualImportError",
    "ManualListing",
    "confine_under_roots",
    "execute_manual_import",
    "execute_roots",
    "list_manual_candidates",
]
