"""Search commands: automatic single-issue / series search + scheduled backlog.

Design decision 9. Three entrypoints, all riding the shared
:func:`foragerr.search_ops.pipeline.run_search` (select indexers → engine →
comparator) and recording a grab hand-off for the best approved release:

- :class:`IssueSearchCommand` — one issue, on the ``search`` pool (size 1, so
  indexer politeness is serialized). Grabs the top approved release.
- ``series-search`` (:class:`~foragerr.library.flows.SeriesSearchCommand`, whose
  change-3 inert stub this replaces) — every wanted issue of one series.
- :class:`BacklogSearchCommand` — scheduled walk of ALL wanted issues,
  oldest-first, with a clamped inter-search politeness delay; skips backing-off
  indexers (handled inside ``search_indexer``); restart-safe via the persisted
  command queue.

The grab hand-off is inert until change 5 (:mod:`foragerr.search_ops.grab`).
"""

from __future__ import annotations

import asyncio
import logging
from typing import ClassVar, Literal

from sqlalchemy import func

from foragerr.commands.registry import BaseCommand, register_command, register_handler
from foragerr.commands.service import HandlerContext
from foragerr.config import Settings
from foragerr.indexers.caps import CapsCache
from foragerr.indexers.ratelimit import DEFAULT_MIN_INTERVAL
from foragerr.library.flows._common import SeriesSearchCommand
from foragerr.library.models import IssueRow
from foragerr.library.repo import wanted_issues
from foragerr.providers.backoff import ProviderBackoff
from foragerr.search import Decision

import foragerr.search_ops.pipeline as pipeline
from foragerr.search_ops.grab import enqueue_grab, handoff_from_decision
from foragerr.search_ops.pipeline import run_search

logger = logging.getLogger("foragerr.search_ops.commands")

#: Per-indexer request-spacing floor used by the search commands (the 2 s
#: politeness gate, FRG-IDX-008). Module-level so tests can drop it to 0.
MIN_INTERVAL = DEFAULT_MIN_INTERVAL

#: Documented politeness floor for the backlog inter-search delay (FRG-SRCH-009);
#: the effective delay is clamped UP to this even if configured lower.
BACKLOG_MIN_DELAY_SECONDS = 30


def effective_backlog_delay(settings: Settings | None) -> int:
    """The clamped inter-search delay: never below the documented floor."""
    configured = (
        settings.backlog_search_delay_seconds if settings is not None else 0
    )
    return max(configured, BACKLOG_MIN_DELAY_SECONDS)


async def _politeness_sleep(seconds: float) -> None:
    """Await the inter-search politeness gap (monkeypatched to a no-op in tests)."""
    await asyncio.sleep(seconds)


def _build_infra(ctx: HandlerContext):
    """The outbound factory, back-off ladder, and one caps cache for a run.

    A fresh :class:`CapsCache` per command run is shared across every issue
    that run searches, so caps are probed once per indexer per command rather
    than per issue.
    """
    factory = pipeline.make_indexer_factory(ctx.settings)
    backoff = ProviderBackoff(ctx.db)
    caps_cache = CapsCache()
    return factory, backoff, caps_cache


async def _search_one_issue(
    ctx: HandlerContext,
    *,
    series_id: int,
    issue_id: int,
    factory,
    backoff,
    caps_cache,
) -> Decision | None:
    """Search one issue and record a grab for the best approved release.

    Returns the approved decision that was handed off, or ``None`` when nothing
    was approved (an explainable no-grab — the rejection reasons live on the
    decisions the pipeline produced).
    """
    result = await run_search(
        db=ctx.db,
        settings=ctx.settings,
        factory=factory,
        backoff=backoff,
        caps_cache=caps_cache,
        series_id=series_id,
        issue_id=issue_id,
        path="auto",
        min_interval=MIN_INTERVAL,
    )
    if result is None:
        return None
    approved = result.approved
    if not approved:
        return None
    best = approved[0]  # already comparator-ordered best-first
    await enqueue_grab(ctx, handoff_from_decision(best, issue_id=issue_id))
    return best


async def _wanted_issue_targets(
    ctx: HandlerContext, *, series_id: int | None = None
) -> list[tuple[int, int]]:
    """(series_id, issue_id) for wanted issues, oldest-first (FRG-SRCH-009).

    Oldest-first = ascending release date (store date preferred, cover date
    fallback), then issue id for a stable total order. Scoped to one series
    when ``series_id`` is given (the series-search walk).
    """
    release_date = func.coalesce(IssueRow.store_date, IssueRow.cover_date)
    stmt = wanted_issues().order_by(release_date.asc(), IssueRow.id.asc())
    if series_id is not None:
        stmt = stmt.where(IssueRow.series_id == series_id)
    async with ctx.db.read_session() as session:
        rows = (await session.execute(stmt)).scalars().all()
        return [(row.series_id, row.id) for row in rows]


# --- automatic single-issue search (FRG-SRCH-008) ---------------------------


@register_command
class IssueSearchCommand(BaseCommand):
    """Automatic search for one issue on the ``search`` pool (FRG-SRCH-008)."""

    name: Literal["issue-search"] = "issue-search"
    workload_class: ClassVar[str] = "search"
    series_id: int
    issue_id: int


@register_handler("issue-search")
async def _handle_issue_search(
    command: IssueSearchCommand, ctx: HandlerContext
) -> str:
    factory, backoff, caps_cache = _build_infra(ctx)
    handed_off = await _search_one_issue(
        ctx,
        series_id=command.series_id,
        issue_id=command.issue_id,
        factory=factory,
        backoff=backoff,
        caps_cache=caps_cache,
    )
    if handed_off is None:
        return f"issue {command.issue_id}: no approved release"
    return (
        f"issue {command.issue_id}: grab recorded for "
        f"{handed_off.candidate.guid} (indexer {handed_off.candidate.indexer_id})"
    )


# --- automatic series search (replaces the change-3 inert stub) -------------


async def run_series_search(
    command: SeriesSearchCommand, ctx: HandlerContext
) -> str:
    """Search every wanted issue of one series (FRG-SRCH-008).

    Records a grab hand-off for the best approved release per wanted issue, or
    leaves an explainable no-grab (the decisions carry the rejection reasons).
    Called by the ``series-search`` handler, replacing the change-3 inert stub.
    """
    factory, backoff, caps_cache = _build_infra(ctx)
    targets = await _wanted_issue_targets(ctx, series_id=command.series_id)
    grabbed = 0
    for series_id, issue_id in targets:
        handed_off = await _search_one_issue(
            ctx,
            series_id=series_id,
            issue_id=issue_id,
            factory=factory,
            backoff=backoff,
            caps_cache=caps_cache,
        )
        if handed_off is not None:
            grabbed += 1
    return (
        f"series {command.series_id}: searched {len(targets)} wanted issue(s), "
        f"{grabbed} grab(s) recorded"
    )


# --- scheduled backlog search (FRG-SRCH-009) --------------------------------


@register_command
class BacklogSearchCommand(BaseCommand):
    """Scheduled re-search of every wanted issue, oldest-first (FRG-SRCH-009).

    Runs on the ``search`` pool (serialized). Restart-safe: the command row is
    persisted, so a mid-run process death is re-queued by orphan recovery
    (FRG-SCHED-002) rather than losing progress.
    """

    name: Literal["backlog-search"] = "backlog-search"
    workload_class: ClassVar[str] = "search"
    exclusivity_group: ClassVar[str | None] = "backlog-search"


@register_handler("backlog-search")
async def _handle_backlog_search(
    command: BacklogSearchCommand, ctx: HandlerContext
) -> str:
    factory, backoff, caps_cache = _build_infra(ctx)
    targets = await _wanted_issue_targets(ctx)
    delay = effective_backlog_delay(ctx.settings)
    grabbed = 0
    for index, (series_id, issue_id) in enumerate(targets):
        if index > 0:
            # Serialize per-issue searches with the clamped politeness delay so
            # indexer API limits are respected (FRG-SRCH-009).
            await _politeness_sleep(delay)
        handed_off = await _search_one_issue(
            ctx,
            series_id=series_id,
            issue_id=issue_id,
            factory=factory,
            backoff=backoff,
            caps_cache=caps_cache,
        )
        if handed_off is not None:
            grabbed += 1
    return (
        f"backlog: searched {len(targets)} wanted issue(s) oldest-first "
        f"(delay {delay}s), {grabbed} grab(s) recorded"
    )
