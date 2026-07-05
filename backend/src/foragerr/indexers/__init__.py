"""The indexer domain: provider registry, Newznab client, caps probe, tiered
query generation, hardened XML parsing/normalization, per-indexer rate limiting,
and the search entrypoint (FRG-IDX-001..010, FRG-SEC-002).

Public surface used by the search/release-API area (change 4, area 3):

- :func:`foragerr.indexers.service.search_indexer` — search one indexer for one
  :class:`foragerr.indexers.query.SearchTarget`, honoring the back-off ladder,
  caps, retention, and the tiered query ladder, returning an
  :class:`~foragerr.indexers.service.IndexerSearchOutcome`.
- :func:`foragerr.indexers.repo.select_for_path` — filter rows to a fetch path
  by the three usage toggles (FRG-IDX-002).
- :class:`foragerr.indexers.models.IndexerRow` / ``ReleaseCacheRow``.
- :class:`foragerr.indexers.caps.CapsCache`.
"""

from foragerr.indexers.errors import (
    IndexerAuthError,
    IndexerFailure,
    IndexerLimitError,
    IndexerMalformedError,
    IndexerUnavailable,
)
from foragerr.indexers.models import IndexerRow, ReleaseCacheRow
from foragerr.indexers.query import QuerySpec, SearchTarget, build_queries
from foragerr.indexers.service import IndexerSearchOutcome, search_indexer

__all__ = [
    "IndexerAuthError",
    "IndexerFailure",
    "IndexerLimitError",
    "IndexerMalformedError",
    "IndexerRow",
    "IndexerSearchOutcome",
    "IndexerUnavailable",
    "QuerySpec",
    "ReleaseCacheRow",
    "SearchTarget",
    "build_queries",
    "search_indexer",
]
