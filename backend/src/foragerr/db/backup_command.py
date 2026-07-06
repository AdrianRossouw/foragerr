"""The scheduled ``backup-database`` command + its startup hooks (FRG-DB-009 /
FRG-DB-012 / FRG-DB-010).

The backup rides the existing scheduler/command backbone: a
:class:`BackupDatabaseCommand` in the ``backup`` exclusivity group, registered as
a ``backup-database`` scheduled task by the API area (so it appears in job
history and is force-runnable — "Back up now" is just ``force_run`` of this
task, FRG-SCHED-007). The handler:

1. runs a full ``PRAGMA integrity_check`` (FRG-DB-012) — a failure ABORTS the
   backup (no ``scheduled-*`` directory is written, so a corrupt database is
   never rotated into the pool) and records a persistent ``database`` health
   error; the command fails visibly in job history;
2. otherwise records the clean check (clearing any prior error), writes the
   consistent DB + config copy under ``scheduled-<ts>/``, and prunes the
   scheduled pool to ``db_scheduled_backup_retention``.

This module also exposes the two startup hooks the API area wires:
:func:`restore_marker_startup_hook` (must run FIRST, before the engine opens)
and :func:`quick_check_startup_hook` (after the DB is prepared). Importing the
module registers the command + handler (decorator side-effects), mirroring the
``ddl.commands`` / ``downloads.tracking`` pattern.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, ClassVar, Literal

from fastapi import FastAPI

from foragerr.commands.registry import BaseCommand, register_command, register_handler
from foragerr.commands.service import HandlerContext
from foragerr.config import CONFIG_FILENAME
from foragerr.db.backup import write_scheduled_backup
from foragerr.db.engine import database_path
from foragerr.db.integrity import run_full_integrity_check, run_quick_check
from foragerr.db.restore import apply_restore_marker
from foragerr.health.state import record_integrity

logger = logging.getLogger("foragerr.db.backup_command")

#: Scheduler task + command name (the two are 1:1 for this task).
BACKUP_DATABASE_TASK = "backup-database"

#: Documented minimum interval (1 hour) — the scheduler clamps a smaller
#: configured interval up to this with a warning (FRG-SCHED-006).
BACKUP_MIN_INTERVAL_SECONDS = 3600


@register_command
class BackupDatabaseCommand(BaseCommand):
    """Write a scheduled DB+config backup with rolling retention (FRG-DB-009).

    Single-flight via the ``backup`` exclusivity group; runs on the default
    worker pool off the request path.
    """

    name: Literal["backup-database"] = "backup-database"
    exclusivity_group: ClassVar[str | None] = "backup"


@register_handler("backup-database")
async def _handle_backup_database(
    command: BackupDatabaseCommand, ctx: HandlerContext
) -> str:
    if ctx.settings is None:
        raise RuntimeError("backup-database requires a settings-bearing service")
    config_dir = ctx.settings.config_dir
    db_path = database_path(config_dir)
    config_path = config_dir / CONFIG_FILENAME
    retention = ctx.settings.db_scheduled_backup_retention

    # (1) Pre-backup full integrity check — gates the backup (FRG-DB-012).
    integrity = await ctx.offload(run_full_integrity_check, db_path)
    if not integrity.ok:
        record_integrity(
            ok=False,
            check=integrity.check,
            source="pre-backup",
            detail=integrity.detail,
        )
        # Abort BEFORE any directory is written — never rotate a good backup out
        # for a copy of corruption. The raise fails the job in history.
        raise RuntimeError(
            f"backup aborted: database failed integrity check — {integrity.detail}"
        )
    # A clean pre-backup check clears any prior database health error.
    record_integrity(ok=True, check=integrity.check, source="pre-backup")

    # (2) Write the consistent DB + config copy, then prune the scheduled pool.
    target_dir = await ctx.offload(
        write_scheduled_backup, db_path, config_path, config_dir, retention
    )
    return f"scheduled backup written to {target_dir.name}"


# --- startup hooks (wired by the API area) -----------------------------------


async def restore_marker_startup_hook(app: FastAPI) -> None:
    """Honor a ``/config/restore-from`` marker (FRG-DB-010).

    MUST be registered as the FIRST startup hook — before ``register_database``
    opens the engine / runs migrations — so the swap happens while the DB is
    closed. A no-op when no marker is present.
    """
    settings = app.state.settings
    result = await asyncio.to_thread(apply_restore_marker, settings.config_dir)
    if result is None:
        return
    if result.status == "restored":
        logger.warning(
            "db: startup restore applied from %s (snapshot: %s)",
            result.target,
            result.snapshot_dir,
        )
    else:
        logger.error(
            "db: startup restore refused (%s); booting against the live database",
            result.reason,
        )


async def quick_check_startup_hook(app: FastAPI) -> None:
    """Run ``PRAGMA quick_check`` at startup and record it (FRG-DB-012).

    Registered AFTER ``register_database`` so it checks the prepared database.
    A failure is logged loudly and marks the ``database`` component as an error
    in the health surface; the app still boots so the admin can reach the System
    screen and restore.
    """
    settings = app.state.settings
    db_path = database_path(settings.config_dir)
    result = await asyncio.to_thread(run_quick_check, db_path)
    record_integrity(
        ok=result.ok, check=result.check, source="startup", detail=result.detail
    )
    if not result.ok:
        logger.error(
            "db: startup integrity quick_check FAILED — %s. The application will "
            "still boot so you can restore from a backup (System screen); the "
            "database health component reports an error until a clean check.",
            result.detail,
        )
    else:
        logger.info("db: startup integrity quick_check ok")


# --- scheduled-task registration payload (wired by the API area) -------------


def backup_task_registration(settings: Any) -> dict[str, Any]:
    """Kwargs for ``scheduler.register_task`` for the backup task (FRG-DB-009)."""
    return {
        "name": BACKUP_DATABASE_TASK,
        "command_name": BACKUP_DATABASE_TASK,
        "interval_seconds": settings.db_backup_interval_seconds,
        "min_interval_seconds": BACKUP_MIN_INTERVAL_SECONDS,
    }


async def register_backup_task(scheduler: Any, settings: Any) -> None:
    """Register the ``backup-database`` scheduled task on ``scheduler``."""
    await scheduler.register_task(**backup_task_registration(settings))


__all__ = [
    "BACKUP_DATABASE_TASK",
    "BACKUP_MIN_INTERVAL_SECONDS",
    "BackupDatabaseCommand",
    "backup_task_registration",
    "quick_check_startup_hook",
    "register_backup_task",
    "restore_marker_startup_hook",
]
