"""The one-time credits backfill command (FRG-CRTR-003).

``creators-backfill`` is deliberately just a fan-out over the EXISTING
``refresh-series`` command: it enqueues one deduplicated ``refresh-series`` per
library series so an established library acquires per-issue credits through the
same ingest path a fresh refresh uses — there is no second credits-ingest
mechanism to maintain (design decision 5). Credit reconciliation is already
wired into ``refresh_series`` (change 1), so this command only has to make every
series get refreshed once.

Two trigger surfaces, per FRG-CRTR-003:

* **One-time automatic run** — :func:`creators_backfill_startup_hook` runs at app
  startup AFTER migrations. Guarded by a persisted marker (a single
  ``creators_backfill_done`` row in the existing ``app_state`` key/value table,
  the same idiom as :mod:`foragerr.db.first_run`): if the marker is unset and the
  library has at least one series, it enqueues the command (deduplicated). An
  **empty** library needs no backfill — new series ingest credits natively at
  add/refresh time — so the hook sets the marker without enqueuing anything.

  Marker-timing choice: the marker is set by the HANDLER on successful
  completion, NOT by the startup hook when it enqueues. So a crash between
  enqueue and completion leaves the marker unset and the next startup re-enqueues
  the backfill (idempotent — the refreshes dedup). The empty-library
  short-circuit is the only place the hook sets the marker directly, because no
  handler runs there.

* **Manual force-run** — the command is registered as a scheduled task purely so
  it is force-runnable via the standard task surface
  (``POST /api/v1/system/task/creators-backfill``, FRG-API-014 / FRG-SCHED-007).
  It is NOT a recurring task: the interval is astronomically large and a fresh
  scheduler row is created with ``last_run`` already stamped — atomically, in the
  same insert transaction (``register_task(initial_last_run=...)``) — so the row
  is never observable with ``last_run IS NULL`` and the interval tick (which
  treats NULL as due) never auto-fires it, even if a scheduler loop ticks the
  instant the row lands. The marker-gated startup hook is the sole automatic
  trigger. Force-run runs the handler regardless of the marker — the handler
  never reads the marker, it always does the (idempotent) work.
"""

from __future__ import annotations

import logging
from typing import ClassVar, Literal

from sqlalchemy import func, select, text, update

from foragerr.commands.registry import BaseCommand, register_command, register_handler
from foragerr.commands.service import HandlerContext
from foragerr.creators.models import CreatorRow
from foragerr.db import utcnow
from foragerr.db.first_run import APP_STATE_TABLE
from foragerr.library.models import SeriesRow

logger = logging.getLogger("foragerr.creators.commands")

#: Scheduler task + command name (1:1, like ``backup-database`` / ``pull-refresh``).
CREATORS_BACKFILL_TASK = "creators-backfill"

#: Marker key in ``app_state`` recording that the one-time backfill has completed
#: for this database (presence of the row is the gate; the value is descriptive).
BACKFILL_MARKER_KEY = "creators_backfill_done"
BACKFILL_MARKER_VALUE = "done"

#: Marker key in ``app_state`` recording that the one-time unseed data fix has run
#: for this database (presence of the row is the gate; the value is descriptive).
#: The fix clears the v0.5.0 ≥2-distinct-series-seeded follows now forbidden by
#: FRG-CRTR-004 (owner decision 2026-07-11); it runs at most once per database.
UNSEED_MARKER_KEY = "creators_unseed_done"
UNSEED_MARKER_VALUE = "done"

#: ``triggered_by`` recorded on each fanned-out ``refresh-series`` command so a
#: refresh fired by the backfill is distinguishable in job history (FRG-CRTR-003).
CREATORS_BACKFILL_TRIGGERED_BY = "creators-backfill"

#: ``triggered_by`` recorded on the backfill command itself when the startup hook
#: enqueues it automatically (distinct from ``manual`` force-run / ``scheduled``).
CREATORS_BACKFILL_STARTUP_TRIGGER = "startup"

#: An effectively-infinite interval (~100 years). The scheduler registration
#: exists ONLY to make the task force-runnable; the one-time auto run is the
#: marker-gated startup hook, never the interval tick.
CREATORS_BACKFILL_INTERVAL_SECONDS = 100 * 365 * 24 * 3600


async def is_backfill_complete(db) -> bool:
    """True iff the persisted backfill marker is set for this database."""
    async with db.read_session() as session:
        result = await session.execute(
            text(f"SELECT 1 FROM {APP_STATE_TABLE} WHERE key = :key"),
            {"key": BACKFILL_MARKER_KEY},
        )
        return result.first() is not None


async def _set_backfill_marker(db) -> None:
    """Set the marker idempotently (``WHERE NOT EXISTS`` on the reserved key)."""
    async with db.write_session() as session:
        await session.execute(
            text(
                f"INSERT INTO {APP_STATE_TABLE} (key, value) "
                "SELECT :key, :value "
                f"WHERE NOT EXISTS (SELECT 1 FROM {APP_STATE_TABLE} WHERE key = :key)"
            ),
            {"key": BACKFILL_MARKER_KEY, "value": BACKFILL_MARKER_VALUE},
        )


@register_command
class CreatorsBackfillCommand(BaseCommand):
    """Fan out a deduplicated ``refresh-series`` per library series (FRG-CRTR-003).

    Carries no payload, so a startup auto-enqueue and a manual force-run dedup to
    one queued command (FRG-SCHED-003); the exclusivity group additionally keeps
    two runs from overlapping."""

    name: Literal["creators-backfill"] = "creators-backfill"
    exclusivity_group: ClassVar[str | None] = "creators-backfill"


@register_handler("creators-backfill")
async def _handle_creators_backfill(
    command: CreatorsBackfillCommand, ctx: HandlerContext
) -> str:
    if ctx.commands is None:  # pragma: no cover - always wired by CommandService
        raise RuntimeError("creators-backfill handler needs a CommandService to enqueue")

    async with ctx.db.read_session() as session:
        series_ids = list(
            (await session.execute(select(SeriesRow.id).order_by(SeriesRow.id)))
            .scalars()
            .all()
        )

    for series_id in series_ids:
        # Deduplicated on the command queue (FRG-SCHED-003): a series already
        # queued/started for refresh (e.g. from a concurrent add or pull) is not
        # double-queued. Credit reconciliation rides the refresh (change 1).
        await ctx.commands.enqueue(
            "refresh-series",
            {"series_id": series_id},
            triggered_by=CREATORS_BACKFILL_TRIGGERED_BY,
        )

    # Set the marker only after the fan-out succeeded (see module docstring): a
    # crash before here leaves it unset so the next startup retries. Idempotent,
    # so a force-run over an already-marked database is a harmless no-op set.
    await _set_backfill_marker(ctx.db)

    summary = (
        f"creators backfill: enqueued refresh-series for {len(series_ids)} "
        "library series (deduplicated)"
    )
    logger.info(summary)
    return summary


async def register_creators_backfill_task(scheduler, db) -> None:
    """Register ``creators-backfill`` as a (non-recurring) force-runnable task.

    The task is registered so ``POST /api/v1/system/task/creators-backfill``
    resolves (FRG-API-014). The interval is astronomically large AND a fresh row
    is created with ``last_run`` stamped to "now" ATOMICALLY, in the same insert
    transaction (``register_task(initial_last_run=...)``), so the row is never
    observable with ``last_run IS NULL`` — closing the window a concurrent
    scheduler tick (which treats NULL as due) could otherwise auto-fire in. The
    marker-gated startup hook is the sole automatic trigger. An existing row's
    ``last_run`` (e.g. from a prior force-run) is left untouched.

    ``db`` is retained in the signature for call-site stability but is no longer
    needed here: the stamp now rides ``register_task``'s own write session.
    """
    await scheduler.register_task(
        name=CREATORS_BACKFILL_TASK,
        command_name=CREATORS_BACKFILL_TASK,
        interval_seconds=CREATORS_BACKFILL_INTERVAL_SECONDS,
        min_interval_seconds=CREATORS_BACKFILL_INTERVAL_SECONDS,
        initial_last_run=utcnow(),
    )


async def creators_backfill_startup_hook(app) -> None:
    """One-time credits-backfill trigger at startup (FRG-CRTR-003).

    Registered AFTER the db migration/engine hook (so ``app_state`` and the
    library tables exist) and after ``register_scheduler`` (so ``app.state``
    carries ``scheduler``/``commands``). Registers the force-run task, then, when
    the marker is unset, either sets the marker for an empty library (nothing to
    backfill) or enqueues the deduplicated backfill command.
    """
    db = app.state.db
    await register_creators_backfill_task(app.state.scheduler, db)

    if await is_backfill_complete(db):
        logger.debug("creators backfill: marker already set; skipping auto-run")
        return

    async with db.read_session() as session:
        series_count = await session.scalar(
            select(func.count()).select_from(SeriesRow)
        )

    if not series_count:
        # Empty library: new series credit natively at add/refresh time, so there
        # is nothing to backfill. Set the marker so a later restart never auto-runs.
        await _set_backfill_marker(db)
        logger.info(
            "creators backfill: empty library; marker set, nothing enqueued"
        )
        return

    await app.state.commands.enqueue(
        CREATORS_BACKFILL_TASK,
        triggered_by=CREATORS_BACKFILL_STARTUP_TRIGGER,
    )
    logger.info(
        "creators backfill: enqueued one-time backfill over %d library series",
        series_count,
    )


async def is_unseed_complete(db) -> bool:
    """True iff the persisted unseed-data-fix marker is set for this database."""
    async with db.read_session() as session:
        result = await session.execute(
            text(f"SELECT 1 FROM {APP_STATE_TABLE} WHERE key = :key"),
            {"key": UNSEED_MARKER_KEY},
        )
        return result.first() is not None


async def creators_unseed_startup_hook(app) -> None:
    """One-time data fix clearing v0.5.0-derived follows (FRG-CRTR-004).

    The v0.5.0 backbone seeded ``followed`` for creators crossing a
    ≥2-distinct-series threshold; the owner decision of 2026-07-11 forbids any
    derived follow, so this fix clears exactly those seeded rows — the ones that
    are ``followed`` but were never user-touched (``follow_touched IS NULL``). An
    explicit follow carries the touched marker and is untouched. Marker-gated on
    ``creators_unseed_done`` in ``app_state`` (same idiom as the backfill), so it
    runs at most once per database; the UPDATE and the marker set commit together
    in one write session. Runs even on an empty library — a cheap no-op UPDATE
    plus the marker set — so the marker is always laid down on first boot.

    Registered BEFORE :func:`creators_backfill_startup_hook` in ``create_app`` so
    a first-boot-after-upgrade can never seed-then-unseed within one start:
    seeding no longer exists, but the ordering keeps the fix ahead of any credit
    ingest the backfill fans out (ordering asserted in tests).
    """
    db = app.state.db
    if await is_unseed_complete(db):
        logger.debug("creators unseed: marker already set; skipping data fix")
        return

    async with db.write_session() as session:
        result = await session.execute(
            update(CreatorRow)
            .where(
                CreatorRow.followed.is_(True),
                CreatorRow.follow_touched.is_(None),
            )
            .values(followed=False, followed_at=None)
        )
        cleared = result.rowcount or 0
        # Set the marker in the SAME transaction as the UPDATE, so the fix and its
        # gate commit atomically. ``WHERE NOT EXISTS`` keeps it idempotent.
        await session.execute(
            text(
                f"INSERT INTO {APP_STATE_TABLE} (key, value) "
                "SELECT :key, :value "
                f"WHERE NOT EXISTS (SELECT 1 FROM {APP_STATE_TABLE} WHERE key = :key)"
            ),
            {"key": UNSEED_MARKER_KEY, "value": UNSEED_MARKER_VALUE},
        )

    logger.info(
        "creators unseed: cleared %d derived follow(s) (followed with "
        "follow_touched NULL); marker set",
        cleared,
    )


__all__ = [
    "BACKFILL_MARKER_KEY",
    "BACKFILL_MARKER_VALUE",
    "CREATORS_BACKFILL_INTERVAL_SECONDS",
    "CREATORS_BACKFILL_STARTUP_TRIGGER",
    "CREATORS_BACKFILL_TASK",
    "CREATORS_BACKFILL_TRIGGERED_BY",
    "UNSEED_MARKER_KEY",
    "UNSEED_MARKER_VALUE",
    "CreatorsBackfillCommand",
    "creators_backfill_startup_hook",
    "creators_unseed_startup_hook",
    "is_backfill_complete",
    "is_unseed_complete",
    "register_creators_backfill_task",
]
