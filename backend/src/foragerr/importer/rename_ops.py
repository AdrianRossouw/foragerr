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

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from foragerr.importer import fileops, history
from foragerr.importer.context import ImportContext
from foragerr.importer.evidence import aggregate
from foragerr.importer.pipeline import build_fields
from foragerr.library.models import IssueFileRow, IssueRow, SeriesRow
from foragerr.naming import render_filename
from foragerr.security.paths import safe_join


@dataclass(frozen=True, slots=True)
class RenamePlanEntry:
    """One file's proposed rename (FRG-PP-012)."""

    issue_file_id: int
    issue_id: int
    current_path: str
    new_path: str
    changed: bool


@dataclass(frozen=True, slots=True)
class RenamePlan:
    """A series' rename plan — one entry per library file (FRG-PP-012)."""

    series_id: int
    entries: tuple[RenamePlanEntry, ...]

    @property
    def changed(self) -> tuple[RenamePlanEntry, ...]:
        """Only the entries whose path would actually change (the operations)."""
        return tuple(entry for entry in self.entries if entry.changed)

    def summary(self) -> str:
        return f"renamed={len(self.changed)}/{len(self.entries)}"


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
    """
    entries = [
        RenamePlanEntry(
            issue_file_id=file_id,
            issue_id=issue.id,
            current_path=current_path,
            new_path=(new_path := _new_path_for(series, issue, current_path, ctx)),
            changed=new_path != current_path,
        )
        for file_id, current_path, issue in files
    ]
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
    session: AsyncSession, series: SeriesRow, ctx: ImportContext
) -> RenamePlan:
    """Recompute the plan and apply exactly its changed moves (FRG-PP-012).

    Writes inside the caller's ``write_session``: each moved file's
    ``issue_files.path`` is updated and one ``EVENT_FILE_RENAMED`` history row is
    recorded per rename, carrying the old and new path. Unchanged entries are
    skipped (idempotent). The FS move runs through ``ctx.offload`` when wired.
    """
    files = await load_rename_inputs(session, series.id)
    plan = preview_renames(series, files, ctx)
    for entry in plan.entries:
        if not entry.changed:
            continue
        placed = await _run_fs(
            ctx,
            fileops.place_file,
            entry.current_path,
            entry.new_path,
            mode=fileops.TransferMode.MOVE,
            margin_bytes=ctx.free_space_margin_bytes,
        )
        row = await session.get(IssueFileRow, entry.issue_file_id)
        if row is not None:
            row.path = str(placed)
        history.record_event(
            session,
            event_type=history.EVENT_FILE_RENAMED,
            series_id=series.id,
            issue_id=entry.issue_id,
            source=history.SOURCE_RESCAN,
            data={"old_path": entry.current_path, "new_path": str(placed)},
            now=ctx.now,
        )
    return plan


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
