"""Hand-rolled interval scheduler over the ``scheduled_tasks`` table.

Implements FRG-SCHED-006 (loop tick ≤ 60 s, per-task intervals clamped to
documented minimums with a logged warning, ``last_run`` persisted so the
schedule survives restart) and FRG-SCHED-007 (force-run: enqueue immediately,
trackable command id, timer reset; dedup applies). Deliberately NOT
APScheduler (design decision 5) — schedule state stays inspectable in our
own table.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
from dataclasses import dataclass
from typing import Any

from foragerr.db import Database, ScheduledTaskRow, utcnow
from foragerr.commands.service import CommandRecord, CommandService

logger = logging.getLogger("foragerr.scheduler")

#: Hard ceiling on the loop tick (FRG-SCHED-006).
MAX_TICK_SECONDS = 60


class UnknownTaskError(KeyError):
    """Force-run or lookup of a task that was never registered."""


@dataclass(frozen=True)
class ScheduledTaskDef:
    """In-code definition of a recurring task (persisted state is last_run)."""

    name: str
    command_name: str
    payload: dict[str, Any] | None
    interval_seconds: int  # effective (already clamped)
    min_interval_seconds: int


class IntervalScheduler:
    """One loop task enqueuing due commands each tick."""

    def __init__(
        self,
        db: Database,
        commands: CommandService,
        *,
        tick_seconds: int = MAX_TICK_SECONDS,
    ) -> None:
        self._db = db
        self._commands = commands
        self.tick_seconds = max(1, min(int(tick_seconds), MAX_TICK_SECONDS))
        self._defs: dict[str, ScheduledTaskDef] = {}
        self._stop = asyncio.Event()
        self._loop_task: asyncio.Task[None] | None = None

    # -- registration --------------------------------------------------------

    async def register_task(
        self,
        name: str,
        command_name: str,
        payload: dict[str, Any] | None = None,
        *,
        interval_seconds: int,
        min_interval_seconds: int = 60,
        initial_last_run: dt.datetime | None = None,
    ) -> ScheduledTaskDef:
        """Register a recurring task, clamping the interval to its minimum.

        The persisted row keeps its ``last_run`` across restarts so the task
        fires at ``last_run + interval`` — never immediately-on-every-start.

        ``initial_last_run`` stamps ``last_run`` on a NEWLY-created row, in the
        same transaction that inserts it — so the row is never observable with
        ``last_run IS NULL`` (which the tick treats as "due"). Existing rows keep
        their persisted ``last_run``. Used by the one-shot ``creators-backfill``
        registration, whose only auto-trigger is a marker-gated startup hook, to
        close the enqueue-then-stamp race a live scheduler tick could exploit.
        """
        effective = interval_seconds
        if effective < min_interval_seconds:
            logger.warning(
                "scheduler: task %s interval %ds is below the documented "
                "minimum %ds; clamped to the minimum",
                name,
                interval_seconds,
                min_interval_seconds,
            )
            effective = min_interval_seconds
        definition = ScheduledTaskDef(
            name=name,
            command_name=command_name,
            payload=payload,
            interval_seconds=effective,
            min_interval_seconds=min_interval_seconds,
        )
        self._defs[name] = definition
        async with self._db.write_session() as session:
            row = await session.get(ScheduledTaskRow, name)
            if row is None:
                session.add(
                    ScheduledTaskRow(
                        name=name,
                        interval_seconds=effective,
                        last_run=initial_last_run,
                    )
                )
            else:
                row.interval_seconds = effective  # keep persisted last_run
        return definition

    def task_names(self) -> list[str]:
        return sorted(self._defs)

    def task_definition(self, name: str) -> ScheduledTaskDef:
        try:
            return self._defs[name]
        except KeyError:
            raise UnknownTaskError(name) from None

    # -- loop ------------------------------------------------------------------

    async def start(self) -> None:
        self._stop = asyncio.Event()
        self._loop_task = asyncio.create_task(self._run(), name="scheduler-loop")
        logger.info(
            "scheduler: loop started (tick=%ds, tasks=%s)",
            self.tick_seconds,
            self.task_names(),
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._loop_task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._loop_task
            self._loop_task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.tick()
            except Exception:
                logger.exception("scheduler: tick failed; continuing")
            with contextlib.suppress(asyncio.TimeoutError, TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=self.tick_seconds)

    async def tick(self, now: dt.datetime | None = None) -> list[CommandRecord]:
        """Enqueue every due task's command; persist last_run (FRG-SCHED-006)."""
        now = now or utcnow()
        enqueued: list[CommandRecord] = []
        for definition in list(self._defs.values()):
            async with self._db.read_session() as session:
                row = await session.get(ScheduledTaskRow, definition.name)
            last_run = row.last_run if row is not None else None
            due = last_run is None or (
                last_run + dt.timedelta(seconds=definition.interval_seconds) <= now
            )
            if not due:
                continue
            record = await self._commands.enqueue(
                definition.command_name,
                definition.payload,
                triggered_by="scheduled",
            )
            await self._set_last_run(definition.name, now)
            enqueued.append(record)
        return enqueued

    async def force_run(self, name: str) -> CommandRecord:
        """Enqueue a task's command now and reset its timer (FRG-SCHED-007).

        De-duplication applies: if an equal-bodied command is already
        queued/started its record is returned instead of a duplicate.
        """
        definition = self.task_definition(name)
        record = await self._commands.enqueue(
            definition.command_name,
            definition.payload,
            triggered_by="manual",
        )
        await self._set_last_run(name, utcnow())
        return record

    async def _set_last_run(self, name: str, when: dt.datetime) -> None:
        async with self._db.write_session() as session:
            row = await session.get(ScheduledTaskRow, name)
            if row is not None:
                row.last_run = when

    async def status(self) -> list[dict[str, Any]]:
        """Schedule state for /health and the api area."""
        rows: list[dict[str, Any]] = []
        async with self._db.read_session() as session:
            for definition in self._defs.values():
                row = await session.get(ScheduledTaskRow, definition.name)
                last_run = row.last_run if row is not None else None
                next_run = (
                    last_run + dt.timedelta(seconds=definition.interval_seconds)
                    if last_run is not None
                    else None
                )
                rows.append(
                    {
                        "name": definition.name,
                        "interval_seconds": definition.interval_seconds,
                        "last_run": last_run,
                        "next_run": next_run,
                    }
                )
        return rows
