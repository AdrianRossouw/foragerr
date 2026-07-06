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
from foragerr.downloads.imports import build_import_context
from foragerr.downloads.models import TrackedDownloadRow
from foragerr.downloads.repo import load_mappings
from foragerr.importer import (
    IMPORT_FILE_MUTATION_GROUP,
    CompletedDownloadSource,
    ImportCandidate,
    ImportStatus,
    ManualImportSource,
    ManualOverride,
    import_candidate,
)
from foragerr.importer.decisions import decide
from foragerr.importer.pipeline import aggregate_candidate, build_evaluation, gather
from foragerr.library import repo
from foragerr.security.paths import PathConfinementError, validate_under_root

logger = logging.getLogger("foragerr.downloads.manual_import")


class ManualImportError(Exception):
    """A bad manual-import request (unreadable path / unknown download).

    Carries the HTTP status the API surfaces as a typed :class:`ApiError`."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


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


class ManualFileSpec(BaseModel):
    """One picked file's corrected mapping in a manual-import execute request."""

    model_config = ConfigDict(extra="forbid")

    path: str
    series_id: int | None = None
    issue_id: int | None = None
    format: str | None = None


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


async def _execute_roots(db: Database) -> list[str]:
    """Roots a manual-import execute may draw files from: registered library root
    folders plus every tracked download's own output path (so a blocked
    download's staged files are importable)."""
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


def _confine(raw_path: str, roots: list[str]) -> str | None:
    """The realpath of ``raw_path`` if it exists under one of ``roots``; else
    ``None``. The single sanctioned containment check (FRG-SEC-004)."""
    if not os.path.exists(raw_path):
        return None
    try:
        return str(validate_under_root(raw_path, roots))
    except PathConfinementError:
        return None


# --- read-only listing (GET) -------------------------------------------------


async def _build_read_source(
    db: Database,
    ctx,
    *,
    path: str | None,
    download_id: str | None,
) -> ManualImportSource:
    if download_id is not None:
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
        completed = CompletedDownloadSource(
            download_id=row.download_id,
            output_path=row.output_path or "",
            client_id=row.client_id,
            client_title=row.title,
            mappings=tuple(mappings),
        )
        return ManualImportSource(download=completed)

    assert path is not None
    if not os.path.exists(path):
        raise ManualImportError(404, f"path does not exist: {path}")
    confined = _confine(path, await _library_roots(db))
    if confined is None:
        raise ManualImportError(
            400, f"path is not under a managed library root: {path}"
        )
    return ManualImportSource(folder_path=confined)


async def list_manual_candidates(
    db: Database,
    settings: Settings | None,
    *,
    path: str | None = None,
    download_id: str | None = None,
    now: dt.datetime | None = None,
) -> list[ManualEntry]:
    """List candidate files with their would-be decisions (FRG-API-015).

    Exactly one of ``path`` / ``download_id`` must be given. Read-only: runs
    ``gather → aggregate → build_evaluation → decide`` per candidate, touching no
    disk beyond archive inspection.
    """
    if (path is None) == (download_id is None):
        raise ManualImportError(
            400, "exactly one of path or downloadId must be supplied"
        )
    now = now or utcnow()
    ctx = await build_import_context(db, settings, now=now)
    source = await _build_read_source(db, ctx, path=path, download_id=download_id)

    entries: list[ManualEntry] = []
    async with db.read_session() as session:
        for candidate in await gather(source, session, ctx):
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
    return entries


# --- execution (POST command) ------------------------------------------------


async def execute_manual_import(
    db: Database,
    settings: Settings | None,
    files: list[ManualFileSpec],
    *,
    offload=None,
    now: dt.datetime | None = None,
) -> str:
    """Import the picked files under their overrides (FRG-PP-016).

    Each file becomes a ``SOURCE_MANUAL`` candidate carrying its override and runs
    the full shared pipeline. Paths are re-confined to a managed root (defence in
    depth even though the API validated them at enqueue): a file outside every
    root is dropped rather than imported from an arbitrary location. Returns an
    ``imported=N blocked=M failed=K`` summary.
    """
    now = now or utcnow()
    ctx = await build_import_context(db, settings, now=now, offload=offload)
    roots = await _execute_roots(db)

    resolved: list[str] = []
    overrides: dict[str, ManualOverride] = {}
    dropped = 0
    for spec in files:
        confined = _confine(spec.path, roots)
        if confined is None:
            dropped += 1
            logger.warning(
                "manual-import: dropping file outside any managed root: %s", spec.path
            )
            continue
        resolved.append(confined)
        overrides[confined] = ManualOverride(
            series_id=spec.series_id, issue_id=spec.issue_id, format=spec.format
        )

    source = ManualImportSource(files=tuple(resolved), overrides=overrides)
    imported = blocked = failed = 0
    async with db.write_session() as session:
        for candidate in await gather(source, session, ctx):
            outcome = await import_candidate(session, candidate, ctx)
            if outcome.status is ImportStatus.IMPORTED:
                imported += 1
            elif outcome.status is ImportStatus.FAILED:
                failed += 1
            else:
                blocked += 1

    summary = f"imported={imported} blocked={blocked} failed={failed}"
    if dropped:
        summary += f" dropped={dropped}"
    logger.info("manual-import: %s", summary)
    return summary


@register_handler("manual-import")
async def _handle_manual_import(
    command: ManualImportCommand, ctx: HandlerContext
) -> str:
    return await execute_manual_import(
        ctx.db, ctx.settings, command.files, offload=ctx.offload
    )


__all__ = [
    "ManualEntry",
    "ManualFileSpec",
    "ManualImportCommand",
    "ManualImportError",
    "execute_manual_import",
    "list_manual_candidates",
]
