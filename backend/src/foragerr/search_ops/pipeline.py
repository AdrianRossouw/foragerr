"""The shared search pipeline: fan a search across indexers, then decide.

One place wires the two merged areas together (design decisions 9-10): select
the indexers a fetch path may use (``foragerr.indexers.repo.select_for_path``),
run each through the self-contained ``search_indexer`` entrypoint, feed every
candidate through the one decision engine (``foragerr.search``), de-duplicate
across indexers, and order the survivors by the comparator chain. Automatic
search, backlog search, and interactive search all call this — so accept/reject
and prioritization behave identically on every path (FRG-SRCH-008/009/014).

The candidate-independent work — selecting indexer rows, resolving per-indexer
retention, and building the series' library snapshot — is split out
(``select_fleet`` + ``prepare_series``) so the search-command loops build it ONCE
per run / per series and reuse it across a series' wanted issues, only varying
the per-issue search target. ``run_search`` composes those pieces for the
single-issue API path.

Provider isolation (FRG-NFR-010): each indexer is searched by its own
``search_indexer`` call (honoring the back-off ladder, bounded timeouts and byte
caps) inside an ``asyncio.gather`` wrapper that maps even an *unexpected* error
to that provider's failure outcome, so one indexer can never wedge the pool or
starve the healthy indexers. A row whose settings fail to load is isolated
earlier still (``select_fleet``) and surfaced as a failed outcome.

Isolation bounds errors; the per-indexer TIME BUDGET (FRG-SRCH-015) bounds
latency. On the interactive path — the only one with a person and a listener
request guard waiting on it — each indexer gets ``effective_search_budget``
seconds; at the deadline the indexers that finished contribute their full
decisions and the stragglers are cancelled and reported as ``timed_out``
outcomes (no back-off penalty: a slow indexer is not a failing one). Scheduled
paths keep the original unbudgeted gather and wait politely.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field, replace
from datetime import datetime

from foragerr.config import (
    SEARCH_BUDGET_CEILING,
    SEARCH_BUDGET_FLOOR,
    SEARCH_BUDGET_LISTENER_MARGIN,
    Settings,
)
from foragerr.db.base import utcnow
from foragerr.http import HttpClientFactory
from foragerr.indexers import IndexerRow, IndexerSearchOutcome, search_indexer
from foragerr.indexers.errors import IndexerUnavailable
from foragerr.indexers.query import SearchTarget as QueryTarget
from foragerr.indexers.ratelimit import DEFAULT_MIN_INTERVAL
from foragerr.indexers.repo import load_indexers, select_for_path
from foragerr.library.models import IssueRow, SeriesRow
from foragerr.providers.backoff import PROVIDER_INDEXER, ProviderBackoff
from foragerr.releases import ReleaseCandidate
from foragerr.search import (
    Decision,
    DecisionEngine,
    EngineConfig,
    EvaluationContext,
    FormatProfile,
    SearchTarget,
    deduplicate,
    order_decisions,
)

from foragerr.search_ops.context import build_evaluation_context

logger = logging.getLogger("foragerr.search_ops.pipeline")

#: One engine instance is stateless and reused across every search.
_ENGINE = DecisionEngine()

#: The one fetch path that is time-budgeted (FRG-SRCH-015): a human is waiting
#: on it behind the listener's request guard. ``rss``/``auto`` (the scheduled
#: backlog and automatic searches) stay politeness-first and unbudgeted.
BUDGETED_PATH = "interactive"

#: How long a cancelled indexer task is given to unwind before the fan-out
#: returns without it. Cancellation lands at the politeness gate's sleep or at
#: the httpx read — both are prompt — so this is insurance, not a wait.
CANCEL_GRACE_SECONDS = 1.0

#: Strong references to cancelled indexer tasks that had not finished unwinding
#: when the fan-out returned, so the loop never destroys a pending task (each
#: entry removes itself on completion). Bounded by the fan-out width.
_STRAGGLERS: set[asyncio.Task] = set()


def make_indexer_factory(settings: Settings) -> HttpClientFactory:
    """Build the outbound HTTP factory for indexer traffic.

    The single indirection tests monkeypatch to route indexer fetches at an
    injected transport instead of the live network (mirrors
    ``library.flows.comicvine_factory``). The release API prefers an
    ``app.state.http_factory`` override before falling back to this.
    """
    return HttpClientFactory(settings)


@dataclass(frozen=True, slots=True)
class SearchResult:
    """The decided output of one issue/series search over all its indexers."""

    #: Every decision (approved, temporarily rejected, rejected), de-duplicated
    #: and ordered best-first by the comparator chain.
    decisions: list[Decision]
    #: Per-indexer outcomes (candidates found, backing-off/failure status) so
    #: callers can surface provider health (FRG-NFR-010).
    indexer_outcomes: list[IndexerSearchOutcome] = field(default_factory=list)
    profile: FormatProfile | None = None
    now: datetime = field(default_factory=utcnow)

    @property
    def approved(self) -> list[Decision]:
        return [d for d in self.decisions if d.approved]


def _retention_days(settings: Settings | None) -> int | None:
    """Global usenet retention in days, or ``None`` when disabled (0)."""
    if settings is None:
        return None
    return settings.usenet_retention_days or None


def _effective_retention(row: IndexerRow, global_days: int | None) -> int | None:
    """A row's effective retention: its override wins over global (FRG-IDX-009)."""
    if row.retention_override is not None:
        return row.retention_override
    return global_days


def _query_target(series: SeriesRow, issue: IssueRow | None) -> QueryTarget:
    """Build the indexer ``q=`` search target from library rows."""
    return QueryTarget(
        series_title=series.title,
        issue_number=issue.issue_number if issue is not None else None,
        year=series.start_year,
    )


def effective_search_budget(settings: Settings | None) -> float | None:
    """The enforced per-indexer interactive budget: the configured value clamped
    into the safe range (with a one-line warning when clamping), mirroring
    :func:`foragerr.metadata.ratelimit.effective_interval` (FRG-SRCH-015).

    The safe range is ``SEARCH_BUDGET_FLOOR`` up to whichever is SMALLER of
    ``SEARCH_BUDGET_CEILING`` and the deployment's own listener request guard
    less ``SEARCH_BUDGET_LISTENER_MARGIN``. The absolute ceiling alone is not
    enough: it is 60 s while the default guard is 30 s, so a configured 31..60
    would sail past the clamp and silently reinstate the 503 the budget exists
    to prevent. Deriving the ceiling from the CONFIGURED guard also means a
    deployment that lowers the guard automatically tightens the budget with it.

    The floor still wins on a pathologically small guard (a 1 s guard would
    otherwise compute a negative ceiling): a budget below the floor cancels
    every indexer before its first page, which is never the more useful failure.

    ``None`` settings (the callers that pass no configuration) mean no budget —
    the unbudgeted fan-out, exactly as before this setting existed."""
    if settings is None:
        return None
    configured = float(settings.indexer_search_time_budget_seconds)
    guard = float(settings.listener_request_timeout_seconds)
    ceiling = max(
        SEARCH_BUDGET_FLOOR,
        min(SEARCH_BUDGET_CEILING, guard - SEARCH_BUDGET_LISTENER_MARGIN),
    )
    clamped = min(max(configured, SEARCH_BUDGET_FLOOR), ceiling)
    if clamped != configured:
        logger.warning(
            "config: indexer_search_time_budget_seconds=%s is outside the safe "
            "range %s..%s (bounded by listener_request_timeout_seconds=%s); "
            "clamped to %s",
            configured,
            SEARCH_BUDGET_FLOOR,
            ceiling,
            guard,
            clamped,
        )
    return clamped


def search_budget_for_path(settings: Settings | None, path: str) -> float | None:
    """The per-indexer time budget for ``path`` — ``None`` when unbudgeted.

    The budget is an INTERACTIVE-path property (design decision D1): a person is
    waiting behind the listener's request guard, so a slow indexer must not hold
    the response. Scheduled work (``auto``/``rss``) has no listener and values
    politeness over latency, so it is never budgeted."""
    if path != BUDGETED_PATH:
        return None
    return effective_search_budget(settings)


def _failed_settings_outcome(row: IndexerRow) -> IndexerSearchOutcome:
    """A failed per-indexer outcome for a row whose settings could not load."""
    return IndexerSearchOutcome(
        indexer_id=row.id,
        indexer_name=row.name,
        failure=IndexerUnavailable("indexer settings failed to load; row skipped"),
    )


@dataclass(frozen=True, slots=True)
class IndexerFleet:
    """The series-independent search infrastructure for one command run.

    Indexer rows and per-indexer retention are the same for every series, so
    this is built ONCE and reused across a whole backlog walk (FRG-IDX-009).
    """

    #: Healthy, path-selected indexer rows to actually search.
    rows: list[IndexerRow]
    #: Pre-built failed outcomes for path-selected rows whose settings could not
    #: load — surfaced on every search's health without ever being queried.
    failed_outcomes: list[IndexerSearchOutcome]
    #: Engine config carrying the per-indexer retention map (FRG-IDX-009).
    config: EngineConfig


@dataclass(frozen=True, slots=True)
class PreparedSeries:
    """The candidate-independent view of one series, reused across its issues.

    Only the per-issue :class:`SearchTarget` varies between wanted issues, so
    the library snapshot (``base_context``) and ``profile`` are built once per
    series (FRG-SRCH-008)."""

    series: SeriesRow
    base_context: EvaluationContext  # target=None; per-issue target stamped on
    profile: FormatProfile


async def select_fleet(db, *, settings: Settings | None, path: str) -> IndexerFleet:
    """Select the path-enabled indexers and build the shared engine config once.

    Corrupt-settings rows are isolated here (skip-and-log) and surfaced as
    failed outcomes rather than aborting the batch (FRG-NFR-010)."""
    listing = await load_indexers(db)
    rows = select_for_path(listing.healthy, path)
    failed_rows = select_for_path(listing.failed, path)
    global_days = _retention_days(settings)
    retention_by_indexer = {
        row.id: _effective_retention(row, global_days) for row in rows
    }
    config = EngineConfig(
        retention_days=global_days, retention_by_indexer=retention_by_indexer
    )
    return IndexerFleet(
        rows=rows,
        failed_outcomes=[_failed_settings_outcome(r) for r in failed_rows],
        config=config,
    )


async def prepare_series(
    db, fleet: IndexerFleet, series_id: int, *, now: datetime | None = None
) -> PreparedSeries | None:
    """Build the reusable per-series context, or ``None`` if the series is gone."""
    async with db.read_session() as session:
        series = await session.get(SeriesRow, series_id)
        if series is None:
            return None
        base_context = await build_evaluation_context(
            session, series, issue_id=None, config=fleet.config, now=now or utcnow()
        )
    if base_context is None:  # pragma: no cover - FK guarantees the profile
        return None
    return PreparedSeries(
        series=series,
        base_context=base_context,
        profile=base_context.library.series[0].profile,
    )


def _being_cancelled() -> bool:
    """Whether the running task has a cancellation in flight.

    ``Task.cancelling()`` counts ``cancel()`` calls the task has not yet
    resolved, so it is true from the moment the budget's cancel is issued right
    through the unwind — which is the whole window in which an incidental
    exception must not be mistaken for a provider failure. Outside a task (a
    direct call in a test or script) there is nothing to be cancelled.
    """
    task = asyncio.current_task()
    return task is not None and task.cancelling() > 0


async def _search_one_indexer(
    row: IndexerRow,
    target: QueryTarget,
    *,
    factory: HttpClientFactory,
    backoff: ProviderBackoff,
    caps_cache,
    retention_days: int | None,
    min_interval: float,
) -> IndexerSearchOutcome:
    """Search one indexer, mapping even an unexpected error to a failed outcome.

    ``search_indexer`` already maps transport/HTTP faults to typed outcomes;
    this wrapper is the last-resort isolation for a genuinely unexpected bug so
    it is attributed to the one indexer (recorded as a back-off failure) and the
    rest of the fan-out still completes (FRG-NFR-005 / FRG-NFR-010)."""
    try:
        return await search_indexer(
            row,
            target,
            factory=factory,
            backoff=backoff,
            caps_cache=caps_cache,
            retention_days=retention_days,
            min_interval=min_interval,
        )
    except Exception as exc:  # noqa: BLE001 — last-resort isolation
        logger.exception(
            "indexer search raised unexpectedly; isolating provider",
            extra={"indexer_id": row.id, "indexer_name": row.name},
        )
        # Penalise the crashing provider on the ladder like any other failure —
        # UNLESS this task is already being cancelled. ``CancelledError`` itself
        # is a ``BaseException`` and passes through untouched, but an ordinary
        # exception raised while a cancelled task unwinds (a client's cleanup
        # blowing up on a half-closed socket) lands here looking exactly like a
        # crash. Recording that would punish a merely SLOW indexer on the
        # back-off ladder, which is precisely what the timeout design refuses to
        # do (FRG-SRCH-015) — and the ``await`` below would be cut short by the
        # pending cancellation anyway. A cancelled context therefore never
        # touches the ladder.
        if _being_cancelled():
            logger.info(
                "indexer search raised while cancelled; leaving the ladder "
                "untouched (a slow indexer is not a failing one)",
                extra={"indexer_id": row.id, "indexer_name": row.name},
            )
        else:
            try:
                await backoff.record_failure(
                    PROVIDER_INDEXER,
                    row.id,
                    reason=f"unexpected error: {type(exc).__name__}",
                )
            except Exception:  # noqa: BLE001 — never let recording mask the search
                logger.exception(
                    "failed to record back-off for crashing indexer",
                    extra={"indexer_id": row.id},
                )
        # ...and synthesize an outcome with a NON-None failure naming the class.
        return IndexerSearchOutcome(
            indexer_id=row.id,
            indexer_name=row.name,
            failure=IndexerUnavailable(
                f"indexer search crashed: {type(exc).__name__}: {exc}"
            ),
        )


def _timed_out_outcome(row: IndexerRow, budget: float) -> IndexerSearchOutcome:
    """The outcome for an indexer cancelled at the budget (FRG-SRCH-015).

    Carries NO failure and NO candidates: the back-off ladder is untouched (a
    slow indexer is not a failing one) and a half-read page is never mixed in."""
    return IndexerSearchOutcome(
        indexer_id=row.id,
        indexer_name=row.name,
        timed_out=True,
        time_budget_seconds=budget,
    )


def _park_straggler(task: asyncio.Task) -> None:
    """Hold a reference to a cancelled task still unwinding, so the event loop
    never garbage-collects a pending task; it drops itself when it finishes.

    Logged, because a task that outlives its grace period is the one thing here
    that is not self-evidently bounded — a parked straggler is invisible to the
    operator otherwise, and a recurring one is a real signal about a provider.
    """
    _STRAGGLERS.add(task)
    task.add_done_callback(_STRAGGLERS.discard)
    logger.info(
        "cancelled indexer search had not unwound within %.1fs; parked",
        CANCEL_GRACE_SECONDS,
        extra={"task": task.get_name(), "parked_total": len(_STRAGGLERS)},
    )


def _rechase_stragglers() -> None:
    """Re-cancel any straggler still parked from an EARLIER fan-out.

    The residual the grace period cannot close: a task that survives its first
    cancel (a client swallowing ``CancelledError`` in a cleanup path, say) would
    otherwise sit in ``_STRAGGLERS`` until the process exits. Re-issuing the
    cancel at the start of every fan-out bounds that — a straggler is chased
    again on the next interactive search rather than merely accumulating — while
    keeping the width bound the set already had: nothing is ever awaited here, so
    this cannot delay the operator's request.
    """
    for task in list(_STRAGGLERS):
        if not task.done():
            task.cancel()


async def _budgeted_fan(
    rows: list[IndexerRow],
    make_search,
    budget: float,
) -> list[IndexerSearchOutcome]:
    """Run each indexer's search as its own task, bounded by ``budget`` seconds.

    Indexers that finished inside the budget contribute their real outcome;
    still-running ones are cancelled and reported as timed out (FRG-SRCH-015).
    Cancellation lands where the indexer is actually waiting — the politeness
    gate's ``asyncio.sleep`` or an httpx read — both of which unwind cleanly:
    the gate's lock is released by its ``async with`` and its last-request
    timestamp is only stamped AFTER the sleep, so a cancelled acquire leaves the
    spacing measured from the last request that really went out (never faster);
    httpx closes the in-flight response on any ``BaseException`` out of ``send``.
    ``asyncio.CancelledError`` is a ``BaseException``, so it also passes
    untouched through the ``except Exception`` isolation in
    :func:`_search_one_indexer` and in the Newznab client — a timeout can never
    be mis-recorded as a provider failure on the back-off ladder.

    Entering, it re-cancels any straggler parked by an earlier fan
    (:func:`_rechase_stragglers`), which is what bounds a task that survived its
    first cancel. Nothing is awaited there, so it cannot cost the operator."""
    if not rows:
        return []  # asyncio.wait() rejects an empty set; nothing to bound
    _rechase_stragglers()
    tasks = [
        asyncio.create_task(make_search(row), name=f"indexer-search-{row.id}")
        for row in rows
    ]
    try:
        _, pending = await asyncio.wait(tasks, timeout=budget)
    except BaseException:
        # The whole request/command was cancelled (shutdown, client hang-up):
        # take the children down with it rather than orphan live searches — and
        # PARK each one, exactly as the budget path does. Cancelling and then
        # dropping the last reference as this frame unwinds is what produces
        # "Task was destroyed but it is pending!" at shutdown; the park holds the
        # reference until the child has actually finished unwinding.
        for task in tasks:
            if not task.done():
                task.cancel()
                _park_straggler(task)
        raise
    if pending:
        for task in pending:
            task.cancel()
        # Give cancellation a moment to land so the sockets close before we
        # return; a straggler beyond that is parked, never awaited into the
        # operator's request.
        await asyncio.wait(pending, timeout=CANCEL_GRACE_SECONDS)

    outcomes: list[IndexerSearchOutcome] = []
    for row, task in zip(rows, tasks, strict=True):
        if task.cancelled() or not task.done():
            logger.info(
                "indexer exceeded the interactive search budget; cancelled",
                extra={
                    "indexer_id": row.id,
                    "indexer_name": row.name,
                    "budget_seconds": budget,
                },
            )
            if not task.done():
                _park_straggler(task)
            outcomes.append(_timed_out_outcome(row, budget))
        else:
            # DELIBERATE: a task that finished in the sliver between
            # ``asyncio.wait`` returning and its cancel being delivered is
            # ``done()`` and not ``cancelled()``, so it lands here and its FULL
            # results are reported as ``searched`` even though it technically
            # missed the deadline by microseconds. Real results in hand beat
            # discarding them to honour a stopwatch — the budget exists to bound
            # the operator's WAIT, and that wait already happened. Not a bug;
            # please do not "fix" it into a timed-out outcome.
            #
            # ``result()`` is wrapped because a task can still carry a stored
            # exception the in-task isolation could not map (an error raised
            # while it unwound, or a BaseException-derived fault): re-raising
            # here would abandon the whole fan-out — every remaining indexer's
            # real results included — over one provider's mess. That is exactly
            # the wedging FRG-NFR-010 forbids, so it becomes THAT indexer's
            # failed outcome and the fan completes.
            try:
                outcomes.append(task.result())
            except BaseException as exc:  # noqa: BLE001 — per-provider isolation
                logger.exception(
                    "indexer search task ended in an unmapped error; isolating "
                    "provider",
                    extra={"indexer_id": row.id, "indexer_name": row.name},
                )
                outcomes.append(
                    IndexerSearchOutcome(
                        indexer_id=row.id,
                        indexer_name=row.name,
                        failure=IndexerUnavailable(
                            f"indexer search ended unexpectedly: "
                            f"{type(exc).__name__}: {exc}"
                        ),
                    )
                )
    return outcomes


async def _fan_search(
    rows: list[IndexerRow],
    target: QueryTarget,
    *,
    factory: HttpClientFactory,
    backoff: ProviderBackoff,
    caps_cache,
    retention_days: int | None,
    min_interval: float,
    time_budget: float | None = None,
) -> tuple[list[ReleaseCandidate], list[IndexerSearchOutcome]]:
    """Search every selected indexer concurrently, isolating each so one cannot
    wedge the others (FRG-NFR-010). Outcomes preserve ``rows`` order; the
    caps-cache and back-off writes are already concurrency-safe.

    ``time_budget`` (interactive path only, FRG-SRCH-015) bounds each indexer's
    share: at the deadline the finished indexers' results are returned and the
    stragglers are cancelled and reported as timed out. Without it the fan-out
    is the original unbudgeted gather — scheduled work waits politely."""

    def make_search(row: IndexerRow):
        return _search_one_indexer(
            row,
            target,
            factory=factory,
            backoff=backoff,
            caps_cache=caps_cache,
            retention_days=retention_days,
            min_interval=min_interval,
        )

    if time_budget is None:
        outcomes = list(await asyncio.gather(*(make_search(row) for row in rows)))
    else:
        outcomes = await _budgeted_fan(rows, make_search, time_budget)
    candidates: list[ReleaseCandidate] = []
    for outcome in outcomes:
        candidates.extend(outcome.candidates)
    return candidates, outcomes


async def search_prepared(
    fleet: IndexerFleet,
    prepared: PreparedSeries,
    *,
    db,
    factory: HttpClientFactory,
    backoff: ProviderBackoff,
    caps_cache,
    issue_id: int | None,
    min_interval: float = DEFAULT_MIN_INTERVAL,
    time_budget: float | None = None,
) -> SearchResult | None:
    """Run one issue's search over a prepared series + fleet, and decide.

    Returns ``None`` when a requested issue no longer exists (or is not this
    series'). Only the per-issue :class:`SearchTarget` varies from the reusable
    ``prepared`` context, stamped on with ``dataclasses.replace``.

    ``time_budget`` is opt-in and defaults to unbudgeted, which is exactly what
    the scheduled backlog/series walks want (they call this directly and never
    pass one). :func:`run_search` derives it from the fetch path so only the
    interactive path is bounded (FRG-SRCH-015)."""
    series = prepared.series
    issue: IssueRow | None = None
    if issue_id is not None:
        async with db.read_session() as session:
            issue = await session.get(IssueRow, issue_id)
        if issue is None or issue.series_id != series.id:
            return None
    query_target = _query_target(series, issue)

    now = utcnow()
    candidates, outcomes = await _fan_search(
        fleet.rows,
        query_target,
        factory=factory,
        backoff=backoff,
        caps_cache=caps_cache,
        retention_days=fleet.config.retention_days,
        min_interval=min_interval,
        time_budget=time_budget,
    )
    outcomes = outcomes + list(fleet.failed_outcomes)

    target = (
        SearchTarget(series_id=series.id, issue_id=issue_id)
        if issue_id is not None
        else None
    )
    context = replace(prepared.base_context, target=target, now=now)

    decisions = _ENGINE.evaluate_all(candidates, context)
    decisions = deduplicate(decisions)
    ordered = order_decisions(decisions, prepared.profile, now)
    return SearchResult(
        decisions=ordered,
        indexer_outcomes=outcomes,
        profile=prepared.profile,
        now=now,
    )


async def run_search(
    *,
    db,
    settings: Settings | None,
    factory: HttpClientFactory,
    backoff: ProviderBackoff,
    caps_cache,
    series_id: int,
    issue_id: int | None,
    path: str,
    min_interval: float = DEFAULT_MIN_INTERVAL,
) -> SearchResult | None:
    """Run one search over ``path``-enabled indexers and decide the results.

    The single-issue API/interactive path: build the fleet + series context and
    search the one issue. Returns ``None`` when the series (or requested issue)
    no longer exists. ``issue_id`` set narrows the query to that issue and
    attaches an engine search target so the search-match specification rejects
    wrong-series / wrong-issue hits (FRG-SRCH-006).

    On the ``interactive`` path each indexer is bounded by the configured time
    budget so a slow provider cannot hold the operator's request past the
    listener guard; every other path stays unbudgeted (FRG-SRCH-015).
    """
    fleet = await select_fleet(db, settings=settings, path=path)
    prepared = await prepare_series(db, fleet, series_id)
    if prepared is None:
        return None
    return await search_prepared(
        fleet,
        prepared,
        db=db,
        factory=factory,
        backoff=backoff,
        caps_cache=caps_cache,
        issue_id=issue_id,
        min_interval=min_interval,
        time_budget=search_budget_for_path(settings, path),
    )
