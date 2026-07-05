"""Persisted command queue, worker pools, recovery, and drain.

Implements FRG-SCHED-001 (lifecycle + validation), FRG-SCHED-002 (persisted
queue, orphan re-queue on startup), FRG-SCHED-003 (dedup among queued/started),
FRG-SCHED-004 (priority order + exclusivity groups), FRG-SCHED-005 (bounded
worker pools per workload class, ``asyncio.to_thread`` offload),
FRG-SCHED-008 (job_history rows + retention pruning), and FRG-SCHED-011
(graceful drain: stop claiming, bounded grace, terminal persistence or
orphan-recovery handoff).
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import datetime as dt
import json
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from sqlalchemy import delete, select

from foragerr.config import Settings
from foragerr.indexers.caps import CapsCache
from foragerr.db import (
    CommandRow,
    Database,
    JobHistoryRow,
    TERMINAL_STATUSES,
    utcnow,
)
from foragerr.commands.registry import (
    BaseCommand,
    get_handler,
    parse_command,
    payload_hash,
    payload_json,
    register_handler,
)
from foragerr.events import EventBus

logger = logging.getLogger("foragerr.commands")

#: Default worker-pool sizes per workload class (design decision 4).
DEFAULT_POOL_SIZES = {"search": 1, "download": 1, "pp": 1, "default": 2}

#: The command a worker is currently executing, so :func:`daemon_offload` can
#: name the abandoned thread when a blocking handler outlives the drain grace.
_current_command: contextvars.ContextVar[str] = contextvars.ContextVar(
    "foragerr_current_command", default="?"
)

#: Thread-name prefix for offloaded blocking work; the shutdown path scans for
#: survivors of this prefix to log the commands abandoned past the drain grace.
OFFLOAD_THREAD_PREFIX = "cmd-offload:"


async def daemon_offload(func: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
    """``asyncio.to_thread``-compatible offload that runs on a DAEMON thread.

    Unlike ``asyncio.to_thread`` (the shared default executor whose non-daemon
    threads Python joins at interpreter exit), a handler that blocks here can
    never wedge shutdown past the drain bound (FRG-DEP-008): the abandoned
    thread dies with the process, and orphan recovery re-runs the command's
    row on the next start (FRG-SCHED-002). The thread is named after the
    running command so the shutdown path can name what it abandoned."""
    loop = asyncio.get_running_loop()
    ctx = contextvars.copy_context()
    future: asyncio.Future[Any] = loop.create_future()

    def _resolve(value: Any) -> None:
        if not future.done():
            future.set_result(value)

    def _reject(exc: BaseException) -> None:
        if not future.done():
            future.set_exception(exc)

    def _run() -> None:
        try:
            result = ctx.run(func, *args, **kwargs)
        except BaseException as exc:  # deliver back to the awaiting coroutine
            loop.call_soon_threadsafe(_reject, exc)
        else:
            loop.call_soon_threadsafe(_resolve, result)

    threading.Thread(
        target=_run,
        name=f"{OFFLOAD_THREAD_PREFIX}{ctx.run(_current_command.get)}",
        daemon=True,
    ).start()
    return await future


@dataclass(frozen=True)
class CommandRecord:
    """Detached snapshot of a command row (safe to use outside sessions)."""

    id: int
    name: str
    status: str
    priority: int
    workload_class: str
    exclusivity_group: str | None
    payload: dict[str, Any]
    payload_hash: str
    triggered_by: str
    queued_at: dt.datetime
    started_at: dt.datetime | None
    finished_at: dt.datetime | None
    result: str | None
    error: str | None

    @classmethod
    def from_row(cls, row: CommandRow) -> "CommandRecord":
        return cls(
            id=row.id,
            name=row.name,
            status=row.status,
            priority=row.priority,
            workload_class=row.workload_class,
            exclusivity_group=row.exclusivity_group,
            payload=json.loads(row.payload),
            payload_hash=row.payload_hash,
            triggered_by=row.triggered_by,
            queued_at=row.queued_at,
            started_at=row.started_at,
            finished_at=row.finished_at,
            result=row.result,
            error=row.error,
        )


@dataclass
class HandlerContext:
    """What every command handler receives alongside its command."""

    db: Database
    bus: EventBus | None
    settings: Settings | None
    offload: Callable[..., Awaitable[Any]]  # asyncio.to_thread-compatible (daemon)
    #: The owning service, so a handler can chain follow-up commands onto the
    #: same persisted backbone (e.g. refresh -> scan). Optional and defaulted
    #: for backwards compatibility with callers that build a bare context;
    #: :class:`CommandService` wires itself in here at construction.
    commands: "CommandService | None" = None
    #: One process-level indexer caps cache, so the search commands share a
    #: single probe cache across runs instead of rebuilding one per command
    #: (FRG-IDX-004). :class:`CommandService` builds it once at construction;
    #: bare contexts default to a fresh cache.
    caps_cache: CapsCache = field(default_factory=CapsCache)


async def prune_job_history(db: Database, retention_days: int) -> int:
    """Delete job_history rows older than the retention window (FRG-SCHED-008)."""
    cutoff = utcnow() - dt.timedelta(days=retention_days)
    async with db.write_session() as session:
        result = await session.execute(
            delete(JobHistoryRow).where(JobHistoryRow.finished_at < cutoff)
        )
    deleted = result.rowcount or 0
    if deleted:
        logger.info("commands: housekeeping pruned %d job_history row(s)", deleted)
    return deleted


class CommandService:
    """Enqueue API + bounded asyncio worker pools over the ``commands`` table."""

    def __init__(
        self,
        db: Database,
        settings: Settings | None = None,
        *,
        bus: EventBus | None = None,
        pool_sizes: dict[str, int] | None = None,
        poll_interval: float = 0.25,
    ) -> None:
        self._db = db
        self._bus = bus
        self._settings = settings
        if pool_sizes is None:
            if settings is not None:
                # Single-source the class list off DEFAULT_POOL_SIZES so the
                # settings-driven mapping can never drift from the fallback.
                pool_sizes = {
                    cls: getattr(settings, f"workers_{cls}")
                    for cls in DEFAULT_POOL_SIZES
                }
            else:
                pool_sizes = dict(DEFAULT_POOL_SIZES)
        self.pool_sizes = pool_sizes
        self._poll_interval = poll_interval
        self._wake = asyncio.Event()
        self._stopping = False
        self._active_groups: set[str] = set()
        self._workers: list[asyncio.Task[None]] = []
        #: Built once here so every search command in this process shares one
        #: caps cache rather than rebuilding a fresh one per run (FRG-IDX-004).
        self.caps_cache = CapsCache()
        self.context = HandlerContext(
            db=db,
            bus=bus,
            settings=settings,
            offload=daemon_offload,
            commands=self,
            caps_cache=self.caps_cache,
        )

    # -- lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        """Orphan recovery (FRG-SCHED-002), then spawn the worker pools."""
        await self.recover_orphans()
        self._stopping = False
        for workload_class, count in self.pool_sizes.items():
            for index in range(count):
                task = asyncio.create_task(
                    self._worker(workload_class),
                    name=f"cmd-worker-{workload_class}-{index}",
                )
                self._workers.append(task)
        logger.info("commands: worker pools started (%s)", self.pool_sizes)

    async def recover_orphans(self) -> int:
        """Re-queue rows left in ``started`` by a dead process (FRG-SCHED-002).

        Each orphan gets an ``interrupted`` job_history row so the recovery is
        visible in the record. Idempotent: a second run finds nothing.
        """
        now = utcnow()
        async with self._db.write_session() as session:
            rows = (
                (
                    await session.execute(
                        select(CommandRow).where(CommandRow.status == "started")
                    )
                )
                .scalars()
                .all()
            )
            for row in rows:
                session.add(
                    JobHistoryRow(
                        command_id=row.id,
                        name=row.name,
                        triggered_by=row.triggered_by,
                        started_at=row.started_at,
                        finished_at=now,
                        outcome="interrupted",
                        error=None,
                    )
                )
                row.status = "queued"
                row.started_at = None
        if rows:
            logger.warning(
                "commands: re-queued %d orphaned started command(s)", len(rows)
            )
        return len(rows)

    async def drain(self, grace_seconds: float) -> None:
        """Graceful drain (FRG-SCHED-011).

        Stops claiming immediately; in-flight handlers get ``grace_seconds``
        to finish (their terminal status is persisted). Anything still
        running after the grace is cancelled and its row stays ``started``
        for the next startup's orphan recovery. Queued rows are untouched.
        """
        self._stopping = True
        self._wake.set()
        if not self._workers:
            return
        done, pending = await asyncio.wait(self._workers, timeout=grace_seconds)
        if pending:
            logger.warning(
                "commands: %d worker(s) exceeded the %.1fs drain grace; "
                "cancelling (rows left for orphan recovery)",
                len(pending),
                grace_seconds,
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        self._workers.clear()
        logger.info("commands: drained (%d finished in grace)", len(done))

    def health(self) -> dict[str, Any]:
        """Scheduler-state component health for /health (api area consumes)."""
        return {
            "status": "stopping" if self._stopping else "up",
            "workers": dict(self.pool_sizes),
            "workers_alive": sum(1 for t in self._workers if not t.done()),
            "active_groups": sorted(self._active_groups),
        }

    # -- enqueue / query -----------------------------------------------------

    async def enqueue(
        self,
        name: str,
        payload: dict[str, Any] | None = None,
        *,
        priority: int | None = None,
        triggered_by: str = "manual",
    ) -> CommandRecord:
        """Validate and enqueue a command; dedup returns the existing one.

        Raises :class:`CommandValidationError` (no row created) for unknown
        names or invalid payloads (FRG-SCHED-001). An equal-bodied command
        already ``queued``/``started`` is returned instead of duplicated
        (FRG-SCHED-003).
        """
        command = parse_command(name, payload)  # may raise, before any DB work
        digest = payload_hash(command)
        async with self._db.write_session() as session:
            existing = (
                (
                    await session.execute(
                        select(CommandRow).where(
                            CommandRow.name == name,
                            CommandRow.payload_hash == digest,
                            CommandRow.status.in_(("queued", "started")),
                        )
                    )
                )
                .scalars()
                .first()
            )
            if existing is not None:
                return CommandRecord.from_row(existing)
            row = CommandRow(
                name=name,
                status="queued",
                priority=priority if priority is not None else command.default_priority,
                workload_class=command.workload_class,
                exclusivity_group=command.exclusivity_group,
                payload=payload_json(command),
                payload_hash=digest,
                triggered_by=triggered_by,
                queued_at=utcnow(),
            )
            session.add(row)
            await session.flush()
            record = CommandRecord.from_row(row)
        self._wake.set()
        return record

    async def get(self, command_id: int) -> CommandRecord | None:
        """Command status lookup (GET /api/v1/command/{id} rides this)."""
        async with self._db.read_session() as session:
            row = await session.get(CommandRow, command_id)
            return CommandRecord.from_row(row) if row is not None else None

    # -- workers ---------------------------------------------------------------

    #: Backoff bounds when a worker iteration raises (e.g. a transient
    #: DatabaseBusyError from ``_claim``): a worker must SELF-HEAL rather than
    #: die and permanently shrink the pool (FRG-SCHED-005).
    _FAILURE_BACKOFF_BASE = 1.0
    _FAILURE_BACKOFF_CAP = 30.0

    async def _worker(self, workload_class: str) -> None:
        consecutive_failures = 0
        while not self._stopping:
            try:
                record = await self._claim(workload_class)
                if record is None:
                    if self._stopping:
                        return
                    with contextlib.suppress(asyncio.TimeoutError, TimeoutError):
                        await asyncio.wait_for(
                            self._wake.wait(), timeout=self._poll_interval
                        )
                    self._wake.clear()
                    consecutive_failures = 0
                    continue
                try:
                    await self._execute(record)
                finally:
                    if record.exclusivity_group:
                        self._active_groups.discard(record.exclusivity_group)
                consecutive_failures = 0
            except asyncio.CancelledError:
                raise  # drain/shutdown: never swallow cancellation
            except Exception:
                # Any other failure (a busy database in _claim or the terminal
                # write, a bug) must not kill the worker — the pool would
                # degrade to zero with no self-heal. Log, back off, carry on.
                consecutive_failures += 1
                backoff = min(
                    self._FAILURE_BACKOFF_BASE * 2 ** (consecutive_failures - 1),
                    self._FAILURE_BACKOFF_CAP,
                )
                logger.exception(
                    "commands: worker %s hit an unexpected error; backing off "
                    "%.1fs then continuing (consecutive failures: %d)",
                    workload_class,
                    backoff,
                    consecutive_failures,
                )
                with contextlib.suppress(asyncio.TimeoutError, TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), timeout=backoff)
                self._wake.clear()

    async def _claim(self, workload_class: str) -> CommandRecord | None:
        """Claim the highest-priority eligible queued row for this class.

        Runs inside the single-writer lock, so the check-and-mark is atomic
        across workers. Rows whose exclusivity group is active are skipped
        (left queued) rather than blocking the worker (FRG-SCHED-004).
        """
        if self._stopping:  # no new claims after a shutdown signal
            return None
        added_group: str | None = None
        try:
            async with self._db.write_session() as session:
                rows = (
                    (
                        await session.execute(
                            select(CommandRow)
                            .where(
                                CommandRow.status == "queued",
                                CommandRow.workload_class == workload_class,
                            )
                            .order_by(
                                CommandRow.priority.desc(), CommandRow.id.asc()
                            )
                            .limit(50)
                        )
                    )
                    .scalars()
                    .all()
                )
                for row in rows:
                    group = row.exclusivity_group
                    if group and group in self._active_groups:
                        continue  # serialized within its group; keep looking
                    if group:
                        self._active_groups.add(group)
                        added_group = group
                    row.status = "started"
                    row.started_at = utcnow()
                    return CommandRecord.from_row(row)
            return None
        except BaseException:
            # If the commit failed AFTER we reserved the group in memory, undo
            # the reservation so a transient error cannot wedge the group's
            # commands out of scheduling forever.
            if added_group is not None:
                self._active_groups.discard(added_group)
            raise

    async def _execute(self, record: CommandRecord) -> None:
        """Run the handler and persist the terminal state + history row.

        A handler exception is captured verbatim on the row; the worker
        carries on (FRG-SCHED-001). Cancellation (drain grace exceeded)
        propagates, leaving the row ``started`` for orphan recovery.
        """
        outcome = "completed"
        error: str | None = None
        result_text: str | None = None
        _current_command.set(f"{record.name}#{record.id}")
        try:
            command = parse_command(record.name, record.payload)
            handler = get_handler(record.name)
            result = await handler(command, self.context)
            if result is not None:
                result_text = (
                    result if isinstance(result, str) else json.dumps(result)
                )
        except asyncio.CancelledError:
            raise  # drain timeout: leave 'started' for recovery (FRG-SCHED-011)
        except Exception as exc:
            outcome = "failed"
            error = str(exc) or repr(exc)  # verbatim (FRG-SCHED-008)
            logger.exception(
                "commands: %s (id=%d) failed", record.name, record.id
            )
        finished = utcnow()
        async with self._db.write_session() as session:
            row = await session.get(CommandRow, record.id)
            if row is not None:
                row.status = outcome
                row.finished_at = finished
                row.result = result_text
                row.error = error
            session.add(
                JobHistoryRow(
                    command_id=record.id,
                    name=record.name,
                    triggered_by=record.triggered_by,
                    started_at=record.started_at,
                    finished_at=finished,
                    outcome=outcome,
                    error=error,
                )
            )


# --- built-in handlers -------------------------------------------------------


@register_handler("noop")
async def _handle_noop(command: BaseCommand, ctx: HandlerContext) -> str:
    """Trivial command used by the api area to exercise POST /command."""
    note = getattr(command, "note", None)
    return note or "ok"


@register_handler("housekeeping")
async def _handle_housekeeping(command: BaseCommand, ctx: HandlerContext) -> str:
    retention_days = (
        ctx.settings.job_history_retention_days if ctx.settings is not None else 30
    )
    pruned = await prune_job_history(ctx.db, retention_days)
    return f"pruned {pruned} job_history row(s)"
