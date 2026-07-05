"""The scheduled DDL queue-processing command (FRG-DDL-007).

A persisted command on the ``download`` workload pool (size 1) inside an
exclusivity group, so ``ddl_queue`` items download strictly one at a time and a
mid-run process death is re-queued by SCHED orphan recovery (FRG-SCHED-002)
before the engine's own :meth:`~foragerr.ddl.queue.DdlQueueEngine.reconcile_orphans`
resets any in-flight row to resumable. The handler is thin glue: build the
engine from the enabled DDL client's settings, reconcile, drain the queue.
"""

from __future__ import annotations

import json
import logging
from typing import ClassVar, Literal

from sqlalchemy import select

from foragerr.commands.registry import BaseCommand, register_command, register_handler
from foragerr.commands.service import HandlerContext
from foragerr.ddl.client import make_ddl_factory, staging_dir_for
from foragerr.ddl.links import parse_host_priority
from foragerr.ddl.queue import DdlQueueEngine
from foragerr.downloads.models import DownloadClientRow
from foragerr.downloads.settings import BuiltinDdlSettings

logger = logging.getLogger("foragerr.ddl.commands")

#: Scheduler task name + interval for periodic queue draining.
PROCESS_DDL_QUEUE_TASK = "process-ddl-queue"
PROCESS_DDL_QUEUE_INTERVAL = 60
PROCESS_DDL_QUEUE_MIN_INTERVAL = 15


@register_command
class ProcessDdlQueueCommand(BaseCommand):
    """Drain the ``ddl_queue`` one item at a time (FRG-DDL-007).

    ``download`` pool (size 1) + an exclusivity group keep it single-flight;
    restart-safe via the persisted command row + orphan recovery.
    """

    name: Literal["process-ddl-queue"] = "process-ddl-queue"
    workload_class: ClassVar[str] = "download"
    exclusivity_group: ClassVar[str | None] = "ddl-queue"


async def _load_ddl_settings(db) -> BuiltinDdlSettings:
    """The enabled DDL client's settings, or defaults when none is configured."""
    async with db.read_session() as session:
        row = (
            await session.execute(
                select(DownloadClientRow)
                .where(
                    DownloadClientRow.implementation == "ddl",
                    DownloadClientRow.enabled.is_(True),
                )
                .order_by(DownloadClientRow.priority.asc(), DownloadClientRow.id.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
    if row is None:
        return BuiltinDdlSettings()
    try:
        return BuiltinDdlSettings.model_validate(json.loads(row.settings))
    except Exception:  # noqa: BLE001 — a corrupt row falls back to defaults
        return BuiltinDdlSettings()


def build_engine(ctx: HandlerContext, settings: BuiltinDdlSettings) -> DdlQueueEngine:
    """Construct the queue engine from a handler context + DDL settings."""
    if ctx.settings is None:
        raise RuntimeError("process-ddl-queue requires a settings-bearing service")
    factory = make_ddl_factory(ctx.settings)
    return DdlQueueEngine(
        ctx.db,
        http_factory=factory,
        staging_dir=staging_dir_for(ctx.settings.config_dir),
        host_priority=parse_host_priority(settings.host_priority),
        prefer_upscaled=settings.prefer_upscaled,
    )


@register_handler("process-ddl-queue")
async def _handle_process_ddl_queue(
    command: ProcessDdlQueueCommand, ctx: HandlerContext
) -> str:
    settings = await _load_ddl_settings(ctx.db)
    engine = build_engine(ctx, settings)
    recovered = await engine.reconcile_orphans()
    processed = await engine.process_all()
    return f"ddl queue: recovered {recovered}, processed {processed} item(s)"


__all__ = [
    "PROCESS_DDL_QUEUE_INTERVAL",
    "PROCESS_DDL_QUEUE_MIN_INTERVAL",
    "PROCESS_DDL_QUEUE_TASK",
    "ProcessDdlQueueCommand",
    "build_engine",
]
