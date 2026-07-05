"""The shared search pipeline: fan a search across indexers, then decide.

One place wires the two merged areas together (design decisions 9-10): select
the indexers a fetch path may use (``foragerr.indexers.repo.select_for_path``),
run each through the self-contained ``search_indexer`` entrypoint, feed every
candidate through the one decision engine (``foragerr.search``), de-duplicate
across indexers, and order the survivors by the comparator chain. Automatic
search, backlog search, and interactive search all call this — so accept/reject
and prioritization behave identically on every path (FRG-SRCH-008/009/014).

Provider isolation (FRG-NFR-010): each indexer is searched by its own
``search_indexer`` call, which honors the back-off ladder, bounded timeouts and
byte caps, and returns a typed outcome rather than raising. This module wraps
each call once more so that even an *unexpected* error from one indexer is
recorded as that provider's failure and never wedges the pool or starves the
healthy indexers in the same search.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from foragerr.config import Settings
from foragerr.db.base import utcnow
from foragerr.http import HttpClientFactory
from foragerr.indexers import IndexerRow, IndexerSearchOutcome, search_indexer
from foragerr.indexers.query import SearchTarget as QueryTarget
from foragerr.indexers.ratelimit import DEFAULT_MIN_INTERVAL
from foragerr.indexers.repo import list_indexers, select_for_path
from foragerr.library.models import IssueRow, SeriesRow
from foragerr.providers.backoff import ProviderBackoff
from foragerr.releases import ReleaseCandidate
from foragerr.search import (
    Decision,
    DecisionEngine,
    EngineConfig,
    FormatProfile,
    deduplicate,
    order_decisions,
)

from foragerr.search_ops.context import build_evaluation_context

logger = logging.getLogger("foragerr.search_ops.pipeline")

#: One engine instance is stateless and reused across every search.
_ENGINE = DecisionEngine()


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


def _query_target(series: SeriesRow, issue: IssueRow | None) -> QueryTarget:
    """Build the indexer ``q=`` search target from library rows."""
    return QueryTarget(
        series_title=series.title,
        issue_number=issue.issue_number if issue is not None else None,
        year=series.start_year,
    )


async def _fan_search(
    rows: list[IndexerRow],
    target: QueryTarget,
    *,
    factory: HttpClientFactory,
    backoff: ProviderBackoff,
    caps_cache,
    retention_days: int | None,
    min_interval: float,
) -> tuple[list[ReleaseCandidate], list[IndexerSearchOutcome]]:
    """Search every selected indexer, isolating each so one cannot wedge the
    others (FRG-NFR-010). Returns all candidates plus per-indexer outcomes."""
    candidates: list[ReleaseCandidate] = []
    outcomes: list[IndexerSearchOutcome] = []
    for row in rows:
        try:
            outcome = await search_indexer(
                row,
                target,
                factory=factory,
                backoff=backoff,
                caps_cache=caps_cache,
                retention_days=retention_days,
                min_interval=min_interval,
            )
        except Exception:  # noqa: BLE001 — last-resort isolation (FRG-NFR-010)
            # search_indexer already maps transport/HTTP faults to typed
            # outcomes; this only catches a genuinely unexpected bug so it is
            # attributed to the one indexer and the search still completes.
            logger.exception(
                "indexer search raised unexpectedly; isolating provider",
                extra={"indexer_id": row.id, "indexer_name": row.name},
            )
            outcome = IndexerSearchOutcome(
                indexer_id=row.id, indexer_name=row.name
            )
        outcomes.append(outcome)
        candidates.extend(outcome.candidates)
    return candidates, outcomes


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

    Returns ``None`` when the series (or a requested issue) no longer exists.
    ``issue_id`` set narrows the query to that issue and attaches an engine
    search target so the search-match specification rejects wrong-series /
    wrong-issue hits (FRG-SRCH-006).
    """
    async with db.read_session() as session:
        series = await session.get(SeriesRow, series_id)
        if series is None:
            return None
        issue = None
        if issue_id is not None:
            issue = await session.get(IssueRow, issue_id)
            if issue is None or issue.series_id != series_id:
                return None
        query_target = _query_target(series, issue)

    rows = select_for_path(await list_indexers(db), path)
    candidates, outcomes = await _fan_search(
        rows,
        query_target,
        factory=factory,
        backoff=backoff,
        caps_cache=caps_cache,
        retention_days=_retention_days(settings),
        min_interval=min_interval,
    )

    now = utcnow()
    config = EngineConfig(retention_days=_retention_days(settings))
    async with db.read_session() as session:
        context = await build_evaluation_context(
            session,
            series_id,
            issue_id=issue_id,
            config=config,
            now=now,
        )
    if context is None:  # series vanished between the two reads
        return None
    profile = context.library.series[0].profile

    decisions = _ENGINE.evaluate_all(candidates, context)
    decisions = deduplicate(decisions)
    ordered = order_decisions(decisions, profile, now)
    return SearchResult(
        decisions=ordered,
        indexer_outcomes=outcomes,
        profile=profile,
        now=now,
    )
