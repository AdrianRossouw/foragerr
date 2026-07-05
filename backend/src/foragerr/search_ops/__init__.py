"""Search commands + interactive-search release API wiring (change 4, area 3).

The integration layer that joins the merged indexers layer
(``foragerr.indexers``) to the merged decision engine (``foragerr.search``):

- the search pipeline (:mod:`foragerr.search_ops.pipeline`) — select indexers →
  ``search_indexer`` per provider → engine → dedup → comparator;
- the search commands (:mod:`foragerr.search_ops.commands`) — automatic
  single-issue / series search and the scheduled backlog walk (FRG-SRCH-008/009);
- the grab hand-off (:mod:`foragerr.search_ops.grab`) — the recorded,
  inert-until-change-5 intent to download (FRG-SRCH-008/014);
- the interactive-search grab cache (:mod:`foragerr.search_ops.cache`) —
  FRG-SRCH-014 / FRG-API-008.

Importing this package registers every search/grab/prune command + handler as a
decorator side effect, so ``foragerr.app`` need only import it once.
"""

from __future__ import annotations

from foragerr.search_ops.cache import (
    CACHE_TTL_MINUTES,
    PruneReleaseCacheCommand,
    cache_decisions,
    get_cached,
    prune_expired,
)
from foragerr.search_ops.commands import (
    BACKLOG_MIN_DELAY_SECONDS,
    BacklogSearchCommand,
    IssueSearchCommand,
    effective_backlog_delay,
    run_series_search,
)
from foragerr.search_ops.grab import (
    GrabReleaseCommand,
    enqueue_grab,
    handoff_from_decision,
)
from foragerr.search_ops.pipeline import (
    SearchResult,
    make_indexer_factory,
    run_search,
)

__all__ = [
    "BACKLOG_MIN_DELAY_SECONDS",
    "BacklogSearchCommand",
    "CACHE_TTL_MINUTES",
    "GrabReleaseCommand",
    "IssueSearchCommand",
    "PruneReleaseCacheCommand",
    "SearchResult",
    "cache_decisions",
    "effective_backlog_delay",
    "enqueue_grab",
    "get_cached",
    "handoff_from_decision",
    "make_indexer_factory",
    "prune_expired",
    "run_search",
    "run_series_search",
]
