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

from typing import Callable, Hashable

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


def _collapse(
    decisions: list[Decision], key_fn: Callable[[Decision], Hashable]
) -> list[Decision]:
    """Collapse decisions sharing a ``key_fn`` key, keeping the best (fewest
    rejections, then higher-priority indexer). Survivor order follows first
    appearance so results are stable (both de-dup stages are this same shape)."""
    winners: dict[Hashable, Decision] = {}
    order: list[Hashable] = []
    for decision in decisions:
        key = key_fn(decision)
        current = winners.get(key)
        if current is None:
            winners[key] = decision
            order.append(key)
        elif _preference(decision) < _preference(current):
            winners[key] = decision
    return [winners[k] for k in order]


def _guid_key(decision: Decision) -> tuple[int, str]:
    return (decision.candidate.indexer_id, decision.candidate.guid)


def _title_size_key(decision: Decision) -> tuple[str, int]:
    c = decision.candidate
    return (normalized_title(c.title), _size_bucket(c.size_bytes))


def deduplicate(decisions: list[Decision]) -> list[Decision]:
    """Return the de-duplicated decisions (FRG-SRCH-010)."""
    # Stage 1: per-indexer guid. Stage 2: cross-indexer title + size bucket.
    guid_deduped = _collapse(decisions, _guid_key)
    return _collapse(guid_deduped, _title_size_key)
