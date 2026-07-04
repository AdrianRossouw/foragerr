"""foragerr command backbone (FRG-SCHED-001..009, 011).

Public surface for the api area:

- ``app.state.commands`` (:class:`CommandService`):
  - ``await enqueue(name, payload, priority=None, triggered_by="manual")``
    → :class:`CommandRecord`; raises :class:`CommandValidationError`.
  - ``await get(command_id)`` → :class:`CommandRecord` | None.
  - ``health()`` → worker-pool component status.
- ``app.state.scheduler`` (:class:`IntervalScheduler`): ``force_run(name)``,
  ``task_names()``, ``await status()``.
- ``app.state.events`` (:class:`~foragerr.events.EventBus`).
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from foragerr.commands.registry import (
    BaseCommand,
    CommandValidationError,
    HousekeepingCommand,
    NoOpCommand,
    command_names,
    parse_command,
    payload_hash,
    payload_json,
    register_command,
    register_handler,
)
from foragerr.commands.scheduler import (
    IntervalScheduler,
    ScheduledTaskDef,
    UnknownTaskError,
)
from foragerr.commands.service import (
    CommandRecord,
    CommandService,
    DEFAULT_POOL_SIZES,
    HandlerContext,
    prune_job_history,
)
from foragerr.events import EventBus

logger = logging.getLogger("foragerr.commands")

__all__ = [
    "BaseCommand",
    "CommandRecord",
    "CommandService",
    "CommandValidationError",
    "DEFAULT_POOL_SIZES",
    "HandlerContext",
    "HousekeepingCommand",
    "IntervalScheduler",
    "NoOpCommand",
    "ScheduledTaskDef",
    "UnknownTaskError",
    "command_names",
    "parse_command",
    "payload_hash",
    "payload_json",
    "prune_job_history",
    "register_command",
    "register_handler",
    "register_scheduler",
]

#: Built-in recurring tasks: (task name, command name, interval, minimum).
BUILTIN_SCHEDULED_TASKS = [
    ("housekeeping", "housekeeping", 24 * 3600, 3600),
]


def register_scheduler(app: FastAPI) -> None:
    """Wire the command backbone into the app lifespan (sched extension point).

    Must be registered AFTER the db area: startup consumes ``app.state.db``.
    Startup: event bus + post-commit wiring, orphan recovery, worker pools,
    scheduler loop. Shutdown (reverse order, before db close): scheduler
    stop, bounded-grace drain (FRG-SCHED-011), event-bus drain.
    """

    async def _startup(app: FastAPI) -> None:
        settings = app.state.settings
        db = app.state.db
        bus = EventBus()
        db.event_publisher = bus.publish  # post-commit publication (FRG-DB-007)
        service = CommandService(db, settings, bus=bus)
        await service.start()
        scheduler = IntervalScheduler(
            db, service, tick_seconds=settings.scheduler_tick_seconds
        )
        for name, command_name, interval, minimum in BUILTIN_SCHEDULED_TASKS:
            await scheduler.register_task(
                name,
                command_name,
                interval_seconds=interval,
                min_interval_seconds=minimum,
            )
        await scheduler.start()
        app.state.events = bus
        app.state.commands = service
        app.state.scheduler = scheduler

    async def _shutdown(app: FastAPI) -> None:
        scheduler = getattr(app.state, "scheduler", None)
        if scheduler is not None:
            await scheduler.stop()
        service = getattr(app.state, "commands", None)
        if service is not None:
            await service.drain(app.state.settings.shutdown_grace_seconds)
        bus = getattr(app.state, "events", None)
        if bus is not None:
            await bus.drain()

    app.state.startup_hooks.append(_startup)
    app.state.shutdown_hooks.append(_shutdown)
