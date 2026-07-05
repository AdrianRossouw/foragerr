"""Cross-indexer de-duplication (FRG-SRCH-010).

The same upload frequently appears on several indexers. De-dup runs in two
stages, in this order:

1. **Per-indexer guid** — collapse a guid an indexer returned more than once
   (complements the parse-time guid de-dup in IDX; the engine must not assume
   it already happened).
2. **Cross-indexer** — group by (normalized title, size bucket) and keep one
   copy: the decision with the fewest rejections, then the higher-priority
   indexer (lower ``indexer_priority``), then a deterministic guid tiebreak.

Distinct releases — sharing neither guid nor the title+size key — are never
collapsed. Survivor order follows first appearance so results are stable.
"""

from __future__ import annotations

from .decision import Decision
from .titles import normalized_title

#: Size-bucket granularity for treating two copies as "the same file".
_SIZE_BUCKET_BYTES = 1024 * 1024  # 1 MiB


def _size_bucket(size_bytes: int | None) -> int:
    """Coarse size bucket; unknown sizes share a single sentinel bucket."""
    if size_bytes is None:
        return -1
    return size_bytes // _SIZE_BUCKET_BYTES


def _preference(decision: Decision) -> tuple[int, int, int, str]:
    """Winner-selection key within a duplicate group; smaller wins.

    Fewest rejections, then higher-priority indexer (lower number), then a
    deterministic (indexer_id, guid) tiebreak.
    """
    c = decision.candidate
    return (len(decision.rejections), c.indexer_priority, c.indexer_id, c.guid)


def deduplicate(decisions: list[Decision]) -> list[Decision]:
    """Return the de-duplicated decisions (FRG-SRCH-010)."""
    # Stage 1: per-indexer guid.
    by_guid: dict[tuple[int, str], Decision] = {}
    guid_order: list[tuple[int, str]] = []
    for decision in decisions:
        key = (decision.candidate.indexer_id, decision.candidate.guid)
        current = by_guid.get(key)
        if current is None:
            by_guid[key] = decision
            guid_order.append(key)
        elif _preference(decision) < _preference(current):
            by_guid[key] = decision
    guid_deduped = [by_guid[k] for k in guid_order]

    # Stage 2: cross-indexer by normalized title + size bucket.
    winners: dict[tuple[str, int], Decision] = {}
    cross_order: list[tuple[str, int]] = []
    for decision in guid_deduped:
        c = decision.candidate
        key = (normalized_title(c.title), _size_bucket(c.size_bytes))
        current = winners.get(key)
        if current is None:
            winners[key] = decision
            cross_order.append(key)
        elif _preference(decision) < _preference(current):
            winners[key] = decision
    return [winners[k] for k in cross_order]
