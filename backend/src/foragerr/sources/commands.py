"""The ``source-sync`` command + scheduled/manual sync (FRG-SRC-003/005).

Rides the existing sched/queue backbone (crash-safe, idempotent per
FRG-NFR-007). The scheduled task (default daily, clamped to a 1 h floor) enqueues
a payload-less ``source-sync`` that syncs EVERY connected source; a manual
"Sync now" enqueues ``source-sync`` with a ``source_id`` for exactly one. Both
run under the ``source-sync`` exclusivity group so runs never overlap.

Expiry (FRG-SRC-005): a 401 mid-sync surfaces as :class:`HumbleAuthError`; the
handler flips that source to ``expired``, keeps partial results, and does NOT
retry against the dead session — the source stays ``expired`` (skipped by every
later sync) until the operator re-pastes a cookie. A transient/malformed order is
skipped-and-logged and never crashes the scheduler.

Importing this module registers the command + handler (decorator side effects),
mirroring the ``pull.commands`` bare-import pattern; ``app.py`` appends
``register_source_sync_task`` after the scheduler is up.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar, Literal

from foragerr.commands.registry import BaseCommand, register_command, register_handler
from foragerr.commands.service import HandlerContext
from foragerr.db.base import utcnow
from foragerr.http import HttpClientFactory
from foragerr.sources import repo
from foragerr.sources.humble import (
    HUMBLE_API_BASE,
    HumbleAuthError,
    HumbleMalformedError,
    HumbleUnavailable,
)
from foragerr.sources.models import SourceRow
from foragerr.sources.service import SyncResult, run_sync

logger = logging.getLogger("foragerr.sources.commands")

#: Scheduler task + command name (1:1, like ``pull-refresh``).
SOURCE_SYNC_TASK = "source-sync"

#: Documented minimum interval (1 hour) the scheduler clamps a smaller configured
#: ``source_sync_interval_seconds`` up to — politeness to the store API
#: (FRG-NFR-005). Mirrors ``PULL_REFRESH_MIN_INTERVAL_SECONDS``.
SOURCE_SYNC_MIN_INTERVAL_SECONDS = 3600


def make_humble_factory(settings: Any) -> HttpClientFactory:
    """Build the outbound HTTP factory for Humble traffic.

    A single indirection tests monkeypatch to route the fetch at an injected
    transport instead of the live network (mirrors ``pull.commands
    .make_pull_factory``)."""
    return HttpClientFactory(settings)


@register_command
class SourceSyncCommand(BaseCommand):
    """Sync connected store sources' entitlements (FRG-SRC-003).

    ``source_id`` targets one source (the manual "Sync now"); omitted syncs every
    connected source (the scheduled tick). Single-flight via the ``source-sync``
    exclusivity group."""

    name: Literal["source-sync"] = "source-sync"
    exclusivity_group: ClassVar[str | None] = "source-sync"
    source_id: int | None = None


@register_handler("source-sync")
async def _handle_source_sync(command: SourceSyncCommand, ctx: HandlerContext) -> str:
    settings = ctx.settings
    if settings is None:  # pragma: no cover - always wired by CommandService
        raise RuntimeError("source-sync requires a settings-bearing service")
    factory = make_humble_factory(settings)
    min_interval = float(settings.source_min_request_interval_seconds)
    base_url = settings.humble_base_url

    if command.source_id is not None:
        source = await repo.get_source(ctx.db, command.source_id)
        sources = [source] if source is not None else []
    else:
        sources = await repo.list_sources(ctx.db)

    synced = 0
    expired = 0
    skipped = 0
    for source in sources:
        # Only connected sources are polled — an expired/disconnected source is
        # skipped (this is what makes 401 → expired a stable no-retry state).
        if source.connection_state != "connected":
            skipped += 1
            continue
        outcome = await _sync_one(
            ctx.db, factory, source, min_interval, base_url=base_url
        )
        synced += 1
        if outcome.expired:
            expired += 1
            continue
        # Post-sync enrichment: compute proposed matches for newly discovered
        # comics and (only when the source's auto_sync toggle is ON) auto-accept
        # the confidently matched ones (FRG-SRC-004). Isolated so a proposal/CV
        # hiccup never fails the sync itself.
        try:
            await _enrich(ctx, source)
        except Exception:  # noqa: BLE001 — enrichment is best-effort
            logger.warning(
                "source-sync: enrichment failed for source %s (sync kept)",
                source.id,
                exc_info=True,
            )

    summary = (
        f"source-sync: {synced} source(s) synced, {expired} expired, "
        f"{skipped} skipped"
    )
    logger.info(summary)
    return summary


async def _enrich(ctx: HandlerContext, source: SourceRow) -> None:
    """Compute proposals + run the auto-sync path for one synced source."""
    from foragerr.sources.enrich import enrich_source

    await enrich_source(ctx.db, ctx.settings, source, commands=ctx.commands)


async def _sync_one(
    db,
    factory: HttpClientFactory,
    source: SourceRow,
    min_interval: float,
    *,
    base_url: str = HUMBLE_API_BASE,
) -> SyncResult:
    """Sync one source, converting a mid-sync 401 into the ``expired`` state
    (FRG-SRC-005) — partial results kept, no retry storm."""
    try:
        result = await run_sync(
            db, factory, source, min_interval=min_interval, base_url=base_url
        )
    except HumbleAuthError as exc:
        logger.warning(
            "source-sync: source %s session expired mid-sync; pausing "
            "(reconnect to resume)",
            source.id,
        )
        await _record_sync(
            db, source.id, state="expired", status=f"session expired: {exc}"
        )
        return SyncResult(expired=True)
    except (HumbleUnavailable, HumbleMalformedError) as exc:
        # A transient whole-sync failure (e.g. the order-list call itself failed):
        # leave the source CONNECTED (the cookie may still be good), record the
        # degradation, and let the next scheduled tick retry — never crash the
        # scheduler, never a retry storm (the interval gate is the throttle).
        logger.warning(
            "source-sync: source %s sync failed transiently (%s); left connected",
            source.id,
            exc,
        )
        await _record_sync(
            db, source.id, state="connected", status=f"sync failed: {exc}"
        )
        return SyncResult()
    await _record_sync(db, source.id, state="connected", status=result.summary())
    return result


async def _record_sync(db, source_id: int, *, state: str, status: str) -> None:
    """Persist the last-sync metadata + connection state on the source row."""
    async with db.write_session() as session:
        row = await session.get(SourceRow, source_id)
        if row is not None:
            row.connection_state = state
            row.last_sync_at = utcnow()
            row.last_sync_status = status[:500]


# --- scheduled-task registration (wired by app.py) --------------------------


def source_sync_task_registration(settings: Any) -> dict[str, Any]:
    """Kwargs for ``scheduler.register_task`` for the source-sync task."""
    return {
        "name": SOURCE_SYNC_TASK,
        "command_name": SOURCE_SYNC_TASK,
        "interval_seconds": settings.source_sync_interval_seconds,
        "min_interval_seconds": SOURCE_SYNC_MIN_INTERVAL_SECONDS,
    }


async def register_source_sync_task(scheduler: Any, settings: Any) -> None:
    """Register the ``source-sync`` scheduled task on ``scheduler`` (FRG-SRC-003)."""
    await scheduler.register_task(**source_sync_task_registration(settings))


__all__ = [
    "SOURCE_SYNC_MIN_INTERVAL_SECONDS",
    "SOURCE_SYNC_TASK",
    "SourceSyncCommand",
    "make_humble_factory",
    "register_source_sync_task",
    "source_sync_task_registration",
]
