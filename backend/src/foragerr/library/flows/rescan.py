"""Per-series disk rescan through the shared import pipeline (FRG-SER-010).

The SER-owned trigger around change-6's pipeline. A rescan:

1. removes ``issue_files`` rows whose backing file has vanished from disk — which
   alone returns the now-fileless monitored issue to the derived Wanted state
   (FRG-SER-004: no status column, membership is a query); and
2. routes every *untracked* file under the (bounded-depth) series walk through the
   SAME :func:`~foragerr.importer.pipeline.import_candidate` used by
   completed-download handling — no rescan-only import path (FRG-SER-010,
   FRG-PP-001).

Files already linked to an issue-file record are skipped by
:class:`~foragerr.importer.sources.RescanSource`; unmatched or pipeline-rejected
files are left in place and recorded, with their reason, in the returned
:class:`RescanReport` (never silently ignored). Per-series statistics are derived
(``repo.series_statistics``), so a new ``issue_files`` row is reflected the moment
the transaction commits — nothing to recount.

The importer owns the file move + ``issue_files``/``import_history`` writes; this
flow owns the vanished-file cleanup, the report, and the trigger — the division
the change-6 design draws between SER and PP.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, ClassVar, Literal

from sqlalchemy import select

from foragerr.commands.registry import BaseCommand, register_command, register_handler
from foragerr.commands.service import HandlerContext
from foragerr.config import Settings
from foragerr.db import Database, utcnow
from foragerr.importer import (
    ImportContext,
    ImportStatus,
    RescanSource,
    gather,
    import_candidate,
)
from foragerr.library import repo
from foragerr.library.models import IssueFileRow, IssueRow

logger = logging.getLogger("foragerr.library.flows.rescan")

OffloadFn = Callable[..., Awaitable[Any]]


@register_command
class RescanSeriesCommand(BaseCommand):
    """Rescan one series' folder: clean vanished files, pipeline the rest.

    Runs on the ``pp`` pool so its file moves serialize behind the completed-
    download drain (one importer-owned pool)."""

    name: Literal["rescan-series"] = "rescan-series"
    workload_class: ClassVar[str] = "pp"
    series_id: int
    path_override: str | None = None


@dataclass(frozen=True, slots=True)
class RescanReport:
    """The per-series rescan outcome (FRG-SER-010 scenario 4)."""

    series_id: int
    imported: tuple[str, ...]
    #: ``(file_name, reasons)`` for every unmatched / pipeline-rejected file.
    blocked: tuple[tuple[str, tuple[str, ...]], ...]
    vanished_removed: int
    file_count: int
    issue_count: int

    def summary(self) -> str:
        return (
            f"imported={len(self.imported)} blocked={len(self.blocked)} "
            f"vanished_removed={self.vanished_removed} "
            f"have={self.file_count}/{self.issue_count}"
        )


async def rescan_series(
    db: Database,
    settings: Settings | None,
    series_id: int,
    *,
    path_override: str | None = None,
    offload: OffloadFn | None = None,
    now: dt.datetime | None = None,
) -> RescanReport:
    """Rescan one series and return its :class:`RescanReport` (FRG-SER-010).

    A missing series (deleted between enqueue and run) yields an empty report
    rather than an error. ``offload`` runs the directory walk off the event loop
    when supplied (the handler passes ``ctx.offload``); direct callers may omit it.
    """
    now = now or utcnow()
    async with db.read_session() as session:
        series = await repo.get_series(session, series_id)
        if series is None:
            logger.info("rescan series %d: series gone; skipped", series_id)
            return RescanReport(series_id, (), (), 0, 0, 0)
        walk_path = path_override or series.path
        reference_year = series.start_year or now.year
        # Existing issue-files for this series, for the vanished-file scan.
        existing = (
            (
                await session.execute(
                    select(IssueFileRow.id, IssueFileRow.path)
                    .join(IssueRow, IssueFileRow.issue_id == IssueRow.id)
                    .where(IssueRow.series_id == series_id)
                )
            )
            .all()
        )

    ctx = ImportContext(
        library_root=series.path,
        config_dir=str(settings.config_dir) if settings is not None else ".",
        reference_year=reference_year,
        now=now,
    )

    # Which linked files have vanished (checked off the loop when offloaded).
    def _vanished() -> list[int]:
        return [fid for fid, path in existing if not os.path.exists(path)]

    vanished_ids = await offload(_vanished) if offload is not None else _vanished()

    # Untracked files under the series path → pipeline candidates (read-only walk).
    source = RescanSource(series_id=series_id, path_override=path_override)
    async with db.read_session() as session:
        candidates = await gather(source, session, ctx)

    imported: list[str] = []
    blocked: list[tuple[str, tuple[str, ...]]] = []
    async with db.write_session() as session:
        # 1. Vanished-file cleanup → derived Wanted restoration (FRG-SER-010).
        for fid in vanished_ids:
            await repo.remove_issue_file(session, fid)
        # 2. Route every untracked file through the ONE shared pipeline.
        for candidate in candidates:
            outcome = await import_candidate(session, candidate, ctx)
            if outcome.status is ImportStatus.IMPORTED:
                imported.append(outcome.imported_path or candidate.local_path)
            else:
                blocked.append(
                    (candidate.file_name, outcome.reasons or ("blocked",))
                )
        stats = await repo.series_statistics(session, series_id)

    report = RescanReport(
        series_id=series_id,
        imported=tuple(imported),
        blocked=tuple(blocked),
        vanished_removed=len(vanished_ids),
        file_count=stats.file_count,
        issue_count=stats.issue_count,
    )
    logger.info("rescan series %d: %s", series_id, report.summary())
    return report


@register_handler("rescan-series")
async def _handle_rescan(command: RescanSeriesCommand, ctx: HandlerContext) -> str:
    report = await rescan_series(
        ctx.db,
        ctx.settings,
        command.series_id,
        path_override=command.path_override,
        offload=ctx.offload,
    )
    return report.summary()


__all__ = ["RescanReport", "RescanSeriesCommand", "rescan_series"]
