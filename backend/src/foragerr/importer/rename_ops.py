"""Rename preview + execute for already-imported library files (FRG-PP-012).

The library *re-organization* path, distinct from the initial import path
(:func:`foragerr.importer.pipeline.execute`, which names files directly at import
time). It reuses the exact same builders so a preview can never propose a name the
import path would not (design decisions 1-2):

    aggregate(current basename)  -> Evidence
    pipeline.build_fields(...)   -> RenameFields
    renamer.render_filename(...) -> new basename (under ctx.file_template)
    security.paths.safe_join(...) -> new path under the series folder

:func:`preview_renames` is a **pure function over rows + templates**: it reads the
``issue_files`` rows, computes ``(issue_file_id, current_path, new_path, changed)``
per file, and touches no disk. :func:`execute_renames` **recomputes** that plan
from the same rows + current context (never trusting a client-submitted plan —
keeping preview and execute byte-identical and closing the TOCTOU/tamper gap),
applies exactly the ``current_path → new_path`` moves via
:func:`foragerr.importer.fileops.place_file`, updates ``issue_files.path``, and
writes one ``EVENT_FILE_RENAMED`` history row per renamed file inside the caller's
``write_session`` (the FRG-PP-011 discipline). No-op (unchanged) entries are
excluded from execution, so it is idempotent.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from foragerr.db import Database
from foragerr.importer import fileops, history
from foragerr.importer.context import ImportContext
from foragerr.importer.evidence import aggregate
from foragerr.importer.pipeline import build_fields
from foragerr.library.models import IssueFileRow, IssueRow, SeriesRow
from foragerr.naming import render_filename
from foragerr.security.paths import safe_join

logger = logging.getLogger("foragerr.importer.rename_ops")


@dataclass(frozen=True, slots=True)
class RenamePlanEntry:
    """One file's proposed rename (FRG-PP-012).

    ``changed`` marks an entry whose ``new_path`` differs from ``current_path``.
    ``blocked`` marks a changed entry that CANNOT be safely applied — currently
    only a target-path collision (two distinct files rendering the same
    ``new_path``): applying either would silently overwrite the other, so both
    are blocked with a ``reason`` and excluded from execution (design decision 2,
    data-loss guard).
    """

    issue_file_id: int
    issue_id: int
    current_path: str
    new_path: str
    changed: bool
    blocked: bool = False
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class RenamePlan:
    """A series' rename plan — one entry per library file (FRG-PP-012)."""

    series_id: int
    entries: tuple[RenamePlanEntry, ...]

    @property
    def changed(self) -> tuple[RenamePlanEntry, ...]:
        """The applicable operations: entries that change AND are not blocked."""
        return tuple(e for e in self.entries if e.changed and not e.blocked)

    @property
    def blocked(self) -> tuple[RenamePlanEntry, ...]:
        """Entries that would change but are blocked (e.g. target collision)."""
        return tuple(e for e in self.entries if e.blocked)

    def summary(self) -> str:
        blocked = self.blocked
        base = f"renamed={len(self.changed)}/{len(self.entries)}"
        return f"{base} blocked={len(blocked)}" if blocked else base


def _new_path_for(
    series: SeriesRow, issue: IssueRow, current_path: str, ctx: ImportContext
) -> str:
    """The path :func:`render_filename` + :func:`safe_join` would give this file.

    Evidence (volume/booktype/release group/classification) is parsed from the
    current on-disk name, exactly as the import path parses a candidate's name —
    so re-organization and import agree on the rendered token values."""
    basename = Path(current_path).name
    evidence = aggregate(
        file_name=basename,
        folder_name=Path(series.path).name,
        reference_year=ctx.reference_year,
    )
    fields = build_fields(series, issue, evidence)
    new_name = render_filename(
        fields,
        template=ctx.file_template,
        ext=Path(current_path).suffix,
        enabled=ctx.rename_enabled,
        original=basename,
    )
    return str(safe_join(series.path, new_name))


def preview_renames(
    series: SeriesRow,
    files: list[tuple[int, str, IssueRow]],
    ctx: ImportContext,
) -> RenamePlan:
    """Compute the rename plan for a series without touching disk (FRG-PP-012).

    ``files`` is ``(issue_file_id, current_path, issue)`` per library file (see
    :func:`load_rename_inputs`). Returns a :class:`RenamePlan`; ``changed`` marks
    each entry whose ``new_path`` differs from its ``current_path``.

    Two distinct files that render the SAME ``new_path`` are a target collision:
    applying either move would overwrite the other, so BOTH are marked
    ``blocked`` and excluded from execution rather than silently clobbering a
    library file (design decision 2, data-loss guard).
    """
    raw = [
        (
            file_id,
            issue,
            current_path,
            _new_path_for(series, issue, current_path, ctx),
        )
        for file_id, current_path, issue in files
    ]
    # A new_path claimed by more than one *changed* file is unresolvable — block
    # every file competing for it (never pick a "winner" that overwrites another).
    changed_targets = Counter(
        new_path for _fid, _iss, cur, new_path in raw if new_path != cur
    )
    colliding = {t for t, n in changed_targets.items() if n > 1}
    entries = []
    for file_id, issue, current_path, new_path in raw:
        changed = new_path != current_path
        blocked = changed and new_path in colliding
        entries.append(
            RenamePlanEntry(
                issue_file_id=file_id,
                issue_id=issue.id,
                current_path=current_path,
                new_path=new_path,
                changed=changed,
                blocked=blocked,
                reason=(
                    "target path collides with another file's rename target"
                    if blocked
                    else None
                ),
            )
        )
    return RenamePlan(series_id=series.id, entries=tuple(entries))


async def load_rename_inputs(
    session: AsyncSession, series_id: int
) -> list[tuple[int, str, IssueRow]]:
    """Load ``(issue_file_id, current_path, issue)`` for every file of a series."""
    rows = (
        await session.execute(
            select(IssueFileRow.id, IssueFileRow.path, IssueRow)
            .join(IssueRow, IssueFileRow.issue_id == IssueRow.id)
            .where(IssueRow.series_id == series_id)
            .order_by(IssueFileRow.id)
        )
    ).all()
    return [(file_id, path, issue) for file_id, path, issue in rows]


async def execute_renames(
    db: Database, series: SeriesRow, ctx: ImportContext
) -> RenamePlan:
    """Recompute the plan and apply exactly its changed moves (FRG-PP-012).

    Restructured for safety on two axes the naive single-transaction version
    missed (both data-loss bugs):

    - **Collision-proof ordering (two-phase move).** Every applicable file is
      first staged at a unique temp name *inside its own target directory* — both
      on disk AND in its ``issue_files.path`` row (phase 1); only then is each
      staged file promoted to its final name (phase 2). A swap chain
      (``1.cbz→2.cbz`` while another tracked ``2.cbz→3.cbz``) can therefore never
      have one move clobber a file another has not yet vacated, and — because
      every row sits at a unique temp path between the phases — a final target is
      always free when assigned, so the ``issue_files.path`` uniqueness constraint
      is never transiently violated. Duplicate final targets are already blocked
      by :func:`preview_renames` and never reach here.
    - **Per-file isolation.** Each file's staging and its promotion + history
      event each commit in their OWN ``write_session`` (mirroring the change-6
      import drain), so a mid-batch failure isolates to that one file — every file
      that already completed keeps its committed row, instead of the old
      all-or-nothing transaction rolling back durable rows while the files had
      already moved on disk. A file+row are always moved together (with
      compensation if the DB step fails after the FS move), so neither phase can
      leave a row pointing at a path the file no longer occupies.

    Unchanged entries are skipped (idempotent). FS moves run through
    ``ctx.offload`` when wired. Returns the recomputed plan.
    """
    async with db.read_session() as session:
        files = await load_rename_inputs(session, series.id)
    plan = preview_renames(series, files, ctx)
    operations = [e for e in plan.entries if e.changed and not e.blocked]

    # Phase 1: stage each file at a unique temp name (file + row moved together).
    # A file that fails here (e.g. vanished) is isolated — it keeps its original
    # path and row, and the other operations still proceed.
    staged: list[tuple[RenamePlanEntry, Path]] = []
    for entry in operations:
        temp = _temp_dest(entry)
        if await _move_file_and_row(
            db, ctx, entry.issue_file_id, entry.current_path, temp,
            what=f"staging {entry.current_path}",
        ):
            staged.append((entry, temp))

    # Phase 2: promote each staged temp to its final name and record the rename.
    for entry, temp in staged:
        await _move_file_and_row(
            db, ctx, entry.issue_file_id, str(temp), entry.new_path,
            what=f"promoting {entry.current_path} -> {entry.new_path}",
            event=(series.id, entry.issue_id, entry.current_path),
        )
    return plan


async def _move_file_and_row(
    db: Database,
    ctx: ImportContext,
    issue_file_id: int,
    src: str,
    dst: "str | Path",
    *,
    what: str,
    event: tuple[int, int, str] | None = None,
) -> bool:
    """Move ``src`` → ``dst`` on disk and commit the row's new path in one step.

    Returns ``True`` on success. On an FS failure nothing changed (the file keeps
    its path, the row untouched). If the DB step fails *after* the file moved, the
    move is COMPENSATED (file returned to ``src``) so a row never points at a path
    the file no longer occupies. When ``event`` is given (``series_id``,
    ``issue_id``, ``old_path``) one ``EVENT_FILE_RENAMED`` row is recorded in the
    same transaction as the path update."""
    try:
        placed = await _run_fs(
            ctx,
            fileops.place_file,
            src,
            dst,
            mode=fileops.TransferMode.MOVE,
            margin_bytes=ctx.free_space_margin_bytes,
        )
    except Exception:
        logger.exception("rename: %s failed on disk; skipped (others unaffected)", what)
        return False
    try:
        async with db.write_session() as session:
            await session.execute(
                update(IssueFileRow)
                .where(IssueFileRow.id == issue_file_id)
                .values(path=str(placed))
            )
            if event is not None:
                series_id, issue_id, old_path = event
                history.record_event(
                    session,
                    event_type=history.EVENT_FILE_RENAMED,
                    series_id=series_id,
                    issue_id=issue_id,
                    source=history.SOURCE_RESCAN,
                    data={"old_path": old_path, "new_path": str(placed)},
                    now=ctx.now,
                )
    except Exception:
        logger.exception("rename: %s committed no row; compensating the move", what)
        try:
            await _run_fs(
                ctx,
                fileops.place_file,
                str(placed),
                src,
                mode=fileops.TransferMode.MOVE,
                margin_bytes=ctx.free_space_margin_bytes,
            )
        except Exception:  # pragma: no cover - compensation best-effort
            logger.error("rename: could not restore %s to %s after a failed commit",
                         placed, src)
        return False
    return True


def _temp_dest(entry: RenamePlanEntry) -> Path:
    """A unique staging path in the entry's DESTINATION directory (phase-1 target).

    Placed beside the final name (so phase-2 promotion is an in-directory atomic
    rename) and keyed on the issue-file id so it can never collide with another
    operation's temp or with any final target."""
    final = Path(entry.new_path)
    return final.with_name(f".foragerr-rename.{entry.issue_file_id}{final.suffix}")


async def _run_fs(ctx: ImportContext, func, *args, **kwargs):
    """Run a blocking filesystem op through the context's offload seam (mirrors
    :func:`foragerr.importer.pipeline._run_fs`)."""
    if ctx.offload is not None:
        return await ctx.offload(func, *args, **kwargs)
    return func(*args, **kwargs)


__all__ = [
    "RenamePlan",
    "RenamePlanEntry",
    "execute_renames",
    "load_rename_inputs",
    "preview_renames",
]
