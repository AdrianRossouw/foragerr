"""The ``pull-refresh`` command + scheduled/manual refresh and the
matched-but-missing refresh trigger (FRG-PULL-005 / FRG-PULL-006) — area D of
m3-pull-backbone. This module wires the three landed halves of the pull
backbone into one command that runs on the existing SCHED backbone:

    fetch (area B)  →  store (area A)  →  match (area C)  →  refresh-trigger

* **Fetch (B).** :class:`foragerr.pull.source.PullSourceClient` fetches the
  current, previous, and next release weeks over the hardened ``external`` egress
  profile, on the shared back-off ladder (``PROVIDER_PULL``). A degraded run
  returns an outcome with no weeks and records the failure on the ladder (which
  is what surfaces the pull source as degraded in health) — this handler then
  stores **nothing** and completes with a note, leaving prior weeks intact
  (FRG-PULL-002). A 619 bad-date skips only its week; the other is still stored.
* **Store + match (A, C), transactional per week.** Each successfully fetched
  week is replaced-on-refresh and matched inside ONE ``write_session`` so the
  delete-then-insert and the match writes commit together (FRG-DB-007); a
  failure mid-week rolls the whole week back, never half-replacing it.
* **Refresh trigger (FRG-PULL-005).** For every entry the matcher tied to a
  watched series (``matched_series_id`` set) whose local issue does not exist
  yet (``matched_issue_id`` None), the existing ``refresh-series`` command is
  enqueued (``triggered_by="pull-refresh"``), deduplicated on the command queue
  (FRG-SCHED-003) so a busy pull week enqueues each series at most once. The
  pull side writes **no** issue status (D4): detection is its only action —
  ``refresh-series`` creates the issue, the series' monitor-new-items policy
  (FRG-SER-007) decides wanted, and the normal search grabs it.

**Schedule / throttle / force-run (FRG-PULL-006).** The task rides the interval
scheduler (:mod:`foragerr.commands.scheduler`) exactly like ``backup-database``:
registered from config (``pull_refresh_interval_seconds``, default 4 h) with a
1 h minimum clamped by ``register_task``. The scheduler's own interval gate IS
the re-poll throttle — a scheduled tick only enqueues when the interval has
elapsed since the last run, so it never re-polls the third party faster than the
cadence; a manual force-run (``POST /api/v1/system/task/pull-refresh``,
FRG-API-014 / FRG-SCHED-007) calls ``scheduler.force_run`` which enqueues
immediately regardless of the gate and resets the timer, so it bypasses the
throttle. This realises the FRG-PULL-006 "throttle suppresses only scheduled
fetches, not a manual force-run" scenario using only the frozen scheduler
mechanics (a handler cannot observe ``triggered_by``, so the throttle lives at
the enqueue gate where scheduled and manual already diverge). The handler
additionally honours the shared back-off ladder: while the pull source is
inside a failure cool-down it skips the fetch (the house convention for every
remote-provider fetch path), so a known-down source is not hammered.

Importing this module registers the command + handler (decorator side effects),
mirroring the ``db.backup_command`` / ``downloads.tracking`` bare-import
pattern; ``app.py`` (area D's task-registration lines) appends the
``register_pull_refresh_task`` startup hook after the scheduler is up.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any, ClassVar, Literal

from foragerr.commands.registry import BaseCommand, register_command, register_handler
from foragerr.commands.service import HandlerContext
from foragerr.http import HttpClientFactory
from foragerr.providers.backoff import (
    PROVIDER_PULL,
    PULL_PROVIDER_ID,
    ProviderBackoff,
)
from foragerr.pull import matching, repo
from foragerr.pull.source import PullSourceClient

logger = logging.getLogger("foragerr.pull.commands")

#: Scheduler task + command name (1:1 for this task, like ``backup-database``).
PULL_REFRESH_TASK = "pull-refresh"

#: Documented minimum interval (1 hour) the scheduler clamps a smaller
#: configured ``pull_refresh_interval_seconds`` up to, protecting the unofficial
#: third-party source (FRG-PULL-006, owner decision). Mirrors
#: ``BACKUP_MIN_INTERVAL_SECONDS``.
PULL_REFRESH_MIN_INTERVAL_SECONDS = 3600

#: How the source enqueues its refresh trigger — recorded on the job-history /
#: command row so a ``refresh-series`` fired by the pull backbone is
#: distinguishable from an add-flow or scheduled one (FRG-PULL-005).
PULL_REFRESH_TRIGGERED_BY = "pull-refresh"


def make_pull_factory(settings: Any) -> HttpClientFactory:
    """Build the outbound HTTP factory for pull-source traffic.

    A single indirection tests monkeypatch to route the fetch at an injected
    transport instead of the live network (mirrors
    ``search_ops.pipeline.make_indexer_factory`` /
    ``library.flows.comicvine_factory``)."""
    return HttpClientFactory(settings)


def _fetch_weeks(as_of: dt.date | None = None) -> list[tuple[int, int]]:
    """The ``(week, year)`` ISO pairs to fetch this run: current + previous +
    next release weeks (FRG-PULL-002 widened by FRG-PULL-009), using
    ``isocalendar`` so a year-boundary date resolves to the correct ISO year
    (matching ``projection.current_week``)."""
    as_of = as_of or dt.date.today()
    weeks: list[tuple[int, int]] = []
    for day in (as_of, as_of - dt.timedelta(days=7), as_of + dt.timedelta(days=7)):
        iso_year, iso_week, _ = day.isocalendar()
        pair = (iso_week, iso_year)
        if pair not in weeks:  # defensive: the three are distinct ISO weeks
            weeks.append(pair)
    return weeks


def _week_key(week: int, year: int) -> str:
    """The stored ``pull_entries.week`` key — the SAME ISO year-week shape the
    projection (area E) reads (``projection.current_week``), so a stored week
    joins straight onto the weekly view."""
    return f"{year}-W{week:02d}"


def _future_week(as_of: dt.date | None = None) -> tuple[int, int]:
    """The ``(week, year)`` ISO pair for the *next* release week (FRG-PULL-009),
    in the same ordering :func:`_fetch_weeks` yields — the week whose empty
    payload, 619, or single-week outage is a skip rather than a whole-run
    degrade or a stored empty week."""
    as_of = as_of or dt.date.today()
    iso_year, iso_week, _ = (as_of + dt.timedelta(days=7)).isocalendar()
    return (iso_week, iso_year)


def _future_week_key(as_of: dt.date | None = None) -> str:
    """The stored-week key for the *next* ISO week (FRG-PULL-009) — the week whose
    empty payload is a logged skip rather than a stored empty week or an outage."""
    return _week_key(*_future_week(as_of))


@register_command
class PullRefreshCommand(BaseCommand):
    """Fetch → store → match → refresh-trigger for the weekly pull (FRG-PULL-006).

    Single-flight via the ``pull-refresh`` exclusivity group so two runs never
    overlap; carries no payload, so a scheduled tick and a manual force-run
    dedup to one queued command (FRG-SCHED-003)."""

    name: Literal["pull-refresh"] = "pull-refresh"
    exclusivity_group: ClassVar[str | None] = "pull-refresh"


@register_handler("pull-refresh")
async def _handle_pull_refresh(command: PullRefreshCommand, ctx: HandlerContext) -> str:
    settings = ctx.settings
    if settings is None:
        raise RuntimeError("pull-refresh requires a settings-bearing service")
    # Enabled-gate (FRG-PULL-006): the task stays registered but no-ops cleanly
    # when the operator has not opted in — no third-party traffic (FRG-PULL-002).
    if not settings.pull_enabled:
        return "weekly pull disabled (pull_enabled=false); nothing fetched"
    source_url = (settings.pull_source_url or "").strip()
    if not source_url:
        return "no pull_source_url configured; nothing fetched"
    if ctx.commands is None:  # pragma: no cover - always wired by CommandService
        raise RuntimeError("pull-refresh handler needs a CommandService to enqueue")

    backoff = ProviderBackoff(ctx.db)
    # House convention (FRG-IDX-010): every remote-provider fetch path consults
    # the ladder first and skips a provider inside its failure cool-down, so a
    # known-down source is not re-hit (health already reflects it).
    status = await backoff.status(PROVIDER_PULL, PULL_PROVIDER_ID)
    if status.active:
        return (
            f"pull source backing off ({status.last_reason}); skipped this run "
            f"(retry in {round(status.remaining_seconds)}s)"
        )

    factory = make_pull_factory(settings)
    today = dt.date.today()
    weeks = _fetch_weeks(today)
    future_week = _future_week(today)
    future_key = _week_key(*future_week)
    async with PullSourceClient(factory, source_url, backoff=backoff) as client:
        outcome = await client.fetch_weeks(weeks, future_week=future_week)

    # Degraded run (FRG-PULL-002): no weeks to store, prior data untouched, the
    # ladder already marked the source degraded — complete with a note, no crash.
    if outcome.degraded:
        return (
            f"pull source degraded ({outcome.outage_reason}); stored weeks left "
            "intact, view still renders from local metadata"
        )

    refreshed: set[int] = set()
    stored_entries = 0
    future_skipped = 0
    for week in outcome.weeks:
        week_key = _week_key(week.week, week.year)
        # FRG-PULL-009: an empty payload for the *future* week means the source
        # has no solicited data for it yet — skip that week only (no replace_week
        # write, so a previously stored future week is never clobbered by an empty
        # refresh). Current/previous weeks store normally, and this is NOT an
        # outage (a 619 for the future week is already skipped upstream). An empty
        # current/previous payload keeps its existing store-empty semantics.
        if week_key == future_key and not week.entries:
            future_skipped += 1
            logger.info(
                "pull source: no future-week data for %s yet; skipping that week",
                week_key,
            )
            continue
        # One transaction per week (FRG-DB-007): replace-on-refresh + match
        # commit together, so a mid-week failure never half-replaces the week.
        async with ctx.db.write_session() as session:
            rows = await repo.replace_week(session, week_key, week.entries)
            results = await matching.match_week(session, rows)
        stored_entries += len(rows)
        # FRG-PULL-005 trigger: a matched watched series whose local issue does
        # not exist yet (matched_series_id set, matched_issue_id None) enqueues
        # the EXISTING refresh-series, deduplicated on the queue. The pull side
        # writes no issue status (D4). Enqueue OUTSIDE the write session — the
        # single-writer lock is released, and enqueue opens its own session.
        for result in results:
            if result.matched_series_id is None or result.matched_issue_id is not None:
                continue
            if result.matched_series_id in refreshed:
                continue
            refreshed.add(result.matched_series_id)
            await ctx.commands.enqueue(
                "refresh-series",
                {"series_id": result.matched_series_id},
                triggered_by=PULL_REFRESH_TRIGGERED_BY,
            )

    parts = [
        f"{len(outcome.weeks)} week(s)",
        f"{stored_entries} entries stored",
        f"{len(refreshed)} refresh-series enqueued",
    ]
    if outcome.skipped:
        parts.append(f"{len(outcome.skipped)} week(s) skipped (bad-date)")
    if future_skipped:
        parts.append(f"{future_skipped} future week(s) skipped (no data)")
    if outcome.future_skipped:
        # FRG-PULL-009 Decision 7: a future-week outage was contained to a
        # single-week skip (not a whole-run degrade); the prior future week, if
        # any, was left untouched because it was never returned for storage.
        parts.append(
            f"{len(outcome.future_skipped)} future week(s) skipped (source outage)"
        )
    summary = "pull refresh: " + ", ".join(parts)
    logger.info(summary)
    return summary


# --- scheduled-task registration payload (wired by app.py, area D) -----------


def pull_refresh_task_registration(settings: Any) -> dict[str, Any]:
    """Kwargs for ``scheduler.register_task`` for the pull-refresh task.

    The configured interval is passed through; ``register_task`` clamps it up to
    :data:`PULL_REFRESH_MIN_INTERVAL_SECONDS` with a warning (FRG-PULL-006)."""
    return {
        "name": PULL_REFRESH_TASK,
        "command_name": PULL_REFRESH_TASK,
        "interval_seconds": settings.pull_refresh_interval_seconds,
        "min_interval_seconds": PULL_REFRESH_MIN_INTERVAL_SECONDS,
    }


async def register_pull_refresh_task(scheduler: Any, settings: Any) -> None:
    """Register the ``pull-refresh`` scheduled task on ``scheduler`` (FRG-PULL-006)."""
    await scheduler.register_task(**pull_refresh_task_registration(settings))


__all__ = [
    "PULL_REFRESH_MIN_INTERVAL_SECONDS",
    "PULL_REFRESH_TASK",
    "PULL_REFRESH_TRIGGERED_BY",
    "PullRefreshCommand",
    "make_pull_factory",
    "pull_refresh_task_registration",
    "register_pull_refresh_task",
]
