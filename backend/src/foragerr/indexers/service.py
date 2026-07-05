"""The indexer search entrypoint (FRG-IDX-004..010) — the seam area 3 calls.

:func:`search_indexer` runs one indexer end-to-end for one search target:

1. honor the back-off ladder — a backing-off indexer is skipped and logged, no
   request issued (FRG-IDX-010 / FRG-NFR-005);
2. resolve capabilities from the TTL cache, degrading to conservative defaults
   on probe failure (FRG-IDX-004);
3. generate the tiered ``q=`` query ladder and page each tier under the per-tier
   and hard result caps, passing usenet retention as ``maxage`` (FRG-IDX-005/009);
4. parse each page through the hardened parser into de-duplicated, attributed
   candidates (FRG-IDX-006/007);
5. record success (reset) or the typed failure (escalate/fast-forward) on the
   back-off ladder (FRG-IDX-010).

Area 3 selects rows for a fetch path with
:func:`foragerr.indexers.repo.select_for_path`, then calls this per row (a
misbehaving one cannot wedge the others — each call is self-contained).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from foragerr.http import HttpClientFactory
from foragerr.indexers.caps import CONSERVATIVE_CAPS, Capabilities, CapsCache
from foragerr.indexers.errors import IndexerFailure
from foragerr.indexers.models import IndexerRow
from foragerr.indexers.newznab import NewznabClient
from foragerr.indexers.parse import IndexerContext, parse_newznab_feed
from foragerr.indexers.query import (
    HARD_RESULT_CAP,
    PER_TIER_RESULT_CAP,
    SearchTarget,
    build_queries,
)
from foragerr.indexers.ratelimit import DEFAULT_MIN_INTERVAL
from foragerr.indexers.repo import load_settings, update_caps_snapshot
from foragerr.providers.backoff import PROVIDER_INDEXER, ProviderBackoff
from foragerr.releases import ReleaseCandidate

logger = logging.getLogger("foragerr.indexers.service")

#: Bounded pagination depth per query (FRG-NFR-005 "bounded pagination depth").
MAX_PAGES_PER_QUERY = 20


@dataclass(slots=True)
class IndexerSearchOutcome:
    """The result of searching one indexer for one target."""

    indexer_id: int
    indexer_name: str
    candidates: list[ReleaseCandidate] = field(default_factory=list)
    skipped_items: int = 0
    #: True when the indexer was skipped because it is inside its back-off
    #: window — no request was issued.
    backing_off: bool = False
    #: The typed failure that ended this indexer's search, if any.
    failure: IndexerFailure | None = None
    #: True when capabilities were conservative fallbacks, not a live probe.
    degraded_caps: bool = False


async def _resolve_caps(
    client: NewznabClient, indexer_id: int, caps_cache: CapsCache
) -> Capabilities:
    """Cached caps, probing live on a miss and degrading on probe failure."""
    cached = caps_cache.get(indexer_id)
    if cached is not None:
        return cached
    try:
        caps = await client.caps()
    except IndexerFailure as exc:
        logger.warning(
            "caps probe failed; using conservative defaults",
            extra={"indexer_id": indexer_id, "error": str(exc)},
        )
        caps = CONSERVATIVE_CAPS
    caps_cache.put(indexer_id, caps)
    return caps


def _caps_summary(caps: Capabilities) -> str:
    """A compact JSON snapshot of resolved caps, persisted on the row."""
    return json.dumps(
        {
            "page_size_max": caps.page_size_max,
            "page_size_default": caps.page_size_default,
            "categories": {str(k): v for k, v in caps.categories.items()},
            "search_available": caps.search_available,
            "book_search_available": caps.book_search_available,
            "degraded": caps.degraded,
        },
        sort_keys=True,
    )


async def refresh_caps(
    db,
    row: IndexerRow,
    *,
    factory: HttpClientFactory,
    caps_cache: CapsCache | None = None,
    min_interval: float = DEFAULT_MIN_INTERVAL,
) -> Capabilities:
    """Probe caps on save/test and record the snapshot on the row (FRG-IDX-004).

    A failed probe degrades to conservative defaults and records the degraded
    state on the row rather than blocking configuration."""
    settings_model = load_settings(row.implementation, row.settings)
    async with NewznabClient(
        settings_model, factory, indexer_id=row.id, min_interval=min_interval
    ) as client:
        try:
            caps = await client.caps()
        except IndexerFailure as exc:
            logger.warning(
                "caps probe failed on refresh; recording degraded defaults",
                extra={"indexer_id": row.id, "error": str(exc)},
            )
            caps = CONSERVATIVE_CAPS
    async with db.write_session() as session:
        db_row = await session.get(IndexerRow, row.id)
        if db_row is not None:
            update_caps_snapshot(
                db_row, caps_json=_caps_summary(caps), degraded=caps.degraded
            )
    if caps_cache is not None:
        caps_cache.put(row.id, caps)
    return caps


def _resolve_retention(row: IndexerRow, retention_days: int | None) -> int | None:
    """Per-indexer override wins over the global retention (FRG-IDX-009)."""
    if row.retention_override is not None:
        return row.retention_override
    return retention_days


async def search_indexer(
    row: IndexerRow,
    target: SearchTarget,
    *,
    factory: HttpClientFactory,
    backoff: ProviderBackoff,
    caps_cache: CapsCache,
    retention_days: int | None = None,
    min_interval: float = DEFAULT_MIN_INTERVAL,
) -> IndexerSearchOutcome:
    """Search one indexer for one target (see module docstring for the steps)."""
    outcome = IndexerSearchOutcome(indexer_id=row.id, indexer_name=row.name)

    status = await backoff.status(PROVIDER_INDEXER, row.id)
    if status.active:
        logger.info(
            "skipping indexer inside back-off window",
            extra={
                "indexer_id": row.id,
                "indexer_name": row.name,
                "backoff_seconds": round(status.remaining_seconds, 1),
            },
        )
        outcome.backing_off = True
        return outcome

    settings_model = load_settings(row.implementation, row.settings)
    queries = build_queries(target)
    if not queries:
        return outcome  # nothing to search; no request, no ladder change

    ctx = IndexerContext(
        indexer_id=row.id, indexer_name=row.name, indexer_priority=row.priority
    )
    maxage = _resolve_retention(row, retention_days)
    seen_guids: set[str] = set()

    async with NewznabClient(
        settings_model, factory, indexer_id=row.id, min_interval=min_interval
    ) as client:
        caps = await _resolve_caps(client, row.id, caps_cache)
        outcome.degraded_caps = caps.degraded
        categories = caps.resolve_categories(settings_model.categories)
        page_size = max(1, min(caps.page_size_default, caps.page_size_max))

        try:
            for spec in queries:
                if len(outcome.candidates) >= HARD_RESULT_CAP:
                    break
                await _run_query(
                    client,
                    spec_text=spec.text,
                    tier=spec.tier,
                    categories=categories,
                    page_size=page_size,
                    maxage=maxage,
                    ctx=ctx,
                    seen_guids=seen_guids,
                    outcome=outcome,
                )
        except IndexerFailure as exc:
            outcome.failure = exc
            await backoff.record_failure(
                PROVIDER_INDEXER,
                row.id,
                reason=str(exc),
                retry_after=exc.retry_after,
                fast_forward=exc.fast_forward,
            )
            return outcome

    await backoff.record_success(PROVIDER_INDEXER, row.id)
    return outcome


async def _run_query(
    client: NewznabClient,
    *,
    spec_text: str,
    tier: int,
    categories: list[int],
    page_size: int,
    maxage: int | None,
    ctx: IndexerContext,
    seen_guids: set[str],
    outcome: IndexerSearchOutcome,
) -> None:
    """Page one query tier under the per-tier and hard result caps."""
    tier_count = 0
    offset = 0
    for _ in range(MAX_PAGES_PER_QUERY):
        remaining_hard = HARD_RESULT_CAP - len(outcome.candidates)
        remaining_tier = PER_TIER_RESULT_CAP - tier_count
        if remaining_hard <= 0 or remaining_tier <= 0:
            return
        limit = min(page_size, remaining_hard, remaining_tier)
        raw = await client.search(
            query=spec_text,
            categories=categories,
            offset=offset,
            limit=limit,
            maxage=maxage,
        )
        result = parse_newznab_feed(
            raw, ctx, query_tier=tier, seen_guids=seen_guids
        )
        outcome.candidates.extend(result.candidates)
        outcome.skipped_items += result.skipped
        tier_count += len(result.candidates)
        returned = len(result.candidates) + result.skipped
        if returned == 0 or returned < limit:
            return  # last page for this tier
        offset += returned
