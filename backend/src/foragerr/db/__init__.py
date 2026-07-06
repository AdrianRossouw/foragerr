"""foragerr persistence area (FRG-DB-001..008).

Public surface:

- :class:`Database` — engine + ``read_session()`` / ``write_session()``.
- :func:`queue_event` — post-commit domain-event queueing inside a write.
- :func:`prepare_database` — startup guard/backup/upgrade sequence.
- :func:`register_database` — wires the above into the app lifespan; after
  startup ``app.state.db`` is the live :class:`Database`.
- ORM models for the command backbone tables.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI

from foragerr.db.base import (
    Base,
    IssueNumberText,
    SentinelFreeText,
    SENTINEL_STRINGS,
    StrictDate,
    StrictDateTime,
    StrictInteger,
    utcnow,
)
from foragerr.db.engine import (
    DB_FILENAME,
    Database,
    DatabaseBusyError,
    database_path,
    queue_event,
)
from foragerr.db.migrations import (
    MigrationError,
    PrepareResult,
    SchemaVersionError,
    prepare_database,
)
from foragerr.db.models import (
    COMMAND_STATUSES,
    TERMINAL_STATUSES,
    CommandRow,
    JobHistoryRow,
    ScheduledTaskRow,
)

logger = logging.getLogger("foragerr.db")

__all__ = [
    "Base",
    "COMMAND_STATUSES",
    "CommandRow",
    "Database",
    "DatabaseBusyError",
    "DB_FILENAME",
    "IssueNumberText",
    "JobHistoryRow",
    "MigrationError",
    "PrepareResult",
    "ScheduledTaskRow",
    "SchemaVersionError",
    "SentinelFreeText",
    "SENTINEL_STRINGS",
    "StrictDate",
    "StrictDateTime",
    "StrictInteger",
    "TERMINAL_STATUSES",
    "database_path",
    "prepare_database",
    "queue_event",
    "register_database",
    "utcnow",
]


def register_database(app: FastAPI) -> None:
    """Register db startup/shutdown hooks on the app (db area extension point).

    Startup: migration guard/backup/upgrade (in a thread — Alembic is sync),
    then the async engine, exposed as ``app.state.db``.
    Shutdown: WAL checkpoint + engine dispose (FRG-DEP-008 half).
    """

    async def _startup(app: FastAPI) -> None:
        settings = app.state.settings
        result = await asyncio.to_thread(
            prepare_database,
            settings.config_dir,
            retention=settings.db_backup_retention,
        )
        if result.applied:
            logger.info(
                "db: migrated %s -> %s (applied: %s)",
                result.previous_revision or "base",
                result.head_revision,
                ", ".join(result.applied),
            )
        app.state.db = Database(settings)

    async def _shutdown(app: FastAPI) -> None:
        db = getattr(app.state, "db", None)
        if db is not None:
            await db.close()

    app.state.startup_hooks.append(_startup)
    app.state.shutdown_hooks.append(_shutdown)
