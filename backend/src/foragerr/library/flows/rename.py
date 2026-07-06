"""Per-series rename preview + execute (FRG-PP-012).

The SER-owned trigger around change-6's rename builders (the analogue of
:mod:`foragerr.library.flows.rescan`). :func:`preview_series_renames` computes an
existing→new path plan for a series without touching disk;
:class:`RenameSeriesCommand` executes it — recomputing the plan under the current
templates and applying only the changed moves — on the ``pp`` pool inside the
importer's file-mutation exclusivity group, so a rename can never run concurrently
with an import drain or a rescan (FRG-SER-010).
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Awaitable, Callable, ClassVar, Literal

from foragerr.commands.registry import BaseCommand, register_command, register_handler
from foragerr.commands.service import HandlerContext
from foragerr.config import Settings
from foragerr.db import Database, utcnow
# Import from the importer.context leaf (not the package root) for
# definition-site clarity: this flow needs only the exclusivity-group string +
# ImportContext + the media-management field mapper, so it names their leaf.
# This does NOT avoid loading the pipeline — importing importer.context still
# executes the foragerr.importer package __init__ (parent-package semantics),
# which pulls in the full pipeline + ORM registration regardless. The actual
# flows→importer cycle protection is the isolated-importability subprocess guard
# in tests/test_nfr_startup.py (FRG-NFR-001).
from foragerr.importer.context import (
    IMPORT_FILE_MUTATION_GROUP,
    ImportContext,
    media_management_fields,
)
from foragerr.importer.rename_ops import (
    RenamePlan,
    execute_renames,
    load_rename_inputs,
    preview_renames,
)
from foragerr.library import repo

logger = logging.getLogger("foragerr.library.flows.rename")

OffloadFn = Callable[..., Awaitable[Any]]


@register_command
class RenameSeriesCommand(BaseCommand):
    """Rename one series' library files to the current file template (FRG-PP-012).

    Runs on the ``pp`` pool and shares the importer's file-mutation exclusivity
    group with the completed-download drain and rescan, so a rename can never
    mutate the library concurrently with them (FRG-SER-010)."""

    name: Literal["rename-series"] = "rename-series"
    workload_class: ClassVar[str] = "pp"
    exclusivity_group: ClassVar[str | None] = IMPORT_FILE_MUTATION_GROUP
    series_id: int


def _build_ctx(
    series_path: str,
    reference_year: int,
    settings: Settings | None,
    *,
    now: dt.datetime,
    offload: OffloadFn | None,
) -> ImportContext:
    return ImportContext(
        library_root=series_path,
        config_dir=str(settings.config_dir) if settings is not None else ".",
        reference_year=reference_year,
        now=now,
        offload=offload,
        **media_management_fields(settings),
    )


async def preview_series_renames(
    db: Database,
    settings: Settings | None,
    series_id: int,
    *,
    now: dt.datetime | None = None,
) -> RenamePlan:
    """Compute a series' rename plan without touching disk (FRG-PP-012).

    A missing series yields an empty plan. Read-only — the plan is computed in a
    read session and no filesystem or database mutation occurs."""
    now = now or utcnow()
    async with db.read_session() as session:
        series = await repo.get_series(session, series_id)
        if series is None:
            return RenamePlan(series_id=series_id, entries=())
        reference_year = series.start_year or now.year
        files = await load_rename_inputs(session, series_id)
    ctx = _build_ctx(series.path, reference_year, settings, now=now, offload=None)
    return preview_renames(series, files, ctx)


async def rename_series(
    db: Database,
    settings: Settings | None,
    series_id: int,
    *,
    offload: OffloadFn | None = None,
    now: dt.datetime | None = None,
) -> RenamePlan:
    """Execute a series' renames (FRG-PP-012).

    Recomputes the plan under the current templates and applies exactly the
    changed moves. Each renamed file's ``issue_files.path`` update and its
    ``EVENT_FILE_RENAMED`` row commit in their OWN transaction (per-file
    isolation, see :func:`execute_renames`), so a mid-batch failure never rolls
    back files that already moved on disk. A missing series yields an empty
    plan."""
    now = now or utcnow()
    async with db.read_session() as session:
        series = await repo.get_series(session, series_id)
        if series is None:
            logger.info("rename series %d: series gone; skipped", series_id)
            return RenamePlan(series_id=series_id, entries=())
        reference_year = series.start_year or now.year
    ctx = _build_ctx(series.path, reference_year, settings, now=now, offload=offload)
    plan = await execute_renames(db, series, ctx)
    logger.info("rename series %d: %s", series_id, plan.summary())
    return plan


@register_handler("rename-series")
async def _handle_rename(command: RenameSeriesCommand, ctx: HandlerContext) -> str:
    plan = await rename_series(
        ctx.db, ctx.settings, command.series_id, offload=ctx.offload
    )
    return plan.summary()


__all__ = [
    "RenameSeriesCommand",
    "preview_series_renames",
    "rename_series",
]
