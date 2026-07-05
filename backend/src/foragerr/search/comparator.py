"""Prioritization comparator chain (FRG-SRCH-007).

Among approved candidates for one issue, pick the best via an ordered chain,
first non-zero comparison wins:

1. format-profile rung   (higher preferred format first)
2. indexer priority      (lower number = higher priority, first)
3. query tier            (lower = more specific, first)
4. bucketed usenet age   (fresher first; log buckets so trivial deltas tie)
5. size closeness        (nearer the profile's preferred size first, log-bucketed)

Implemented as a pure sort-*key* function returning a tuple: tuple ordering is
inherently first-non-zero-wins, acyclic, and — with a unique final tiebreak of
(indexer_id, guid) — yields a total, permutation-independent order that a
property test can pin. Preferred-term / release-group scoring (FRG-QUAL-003/004)
and the torrent peer-count comparator are M2 and absent here.
"""

from __future__ import annotations

import math
from datetime import datetime

from .context import FormatProfile
from .decision import Decision
from .titles import candidate_format

#: A very large bucket so undated releases sort after any dated one.
_NO_AGE_BUCKET = 1_000_000


def _age_bucket(pub_date: datetime | None, now: datetime) -> int:
    """Log-bucketed age in hours: fresh ≫ day ≫ week, trivial deltas collapse."""
    if pub_date is None:
        return _NO_AGE_BUCKET
    pub = pub_date.replace(tzinfo=None) if pub_date.tzinfo is not None else pub_date
    now_naive = now.replace(tzinfo=None) if now.tzinfo is not None else now
    hours = max((now_naive - pub).total_seconds() / 3600.0, 0.0)
    return int(math.log2(hours + 1.0))


def _size_closeness_bucket(
    size_bytes: int | None, preferred_size_bytes: int | None
) -> int:
    """Log-bucketed distance from the preferred size; 0 when unconfigured.

    Without a configured preferred size (the M1 default, since per-format size
    bounds are M2) every candidate ties here and ordering falls through.
    """
    if preferred_size_bytes is None or not preferred_size_bytes:
        return 0
    if size_bytes is None or size_bytes <= 0:
        return _NO_AGE_BUCKET
    distance = abs(math.log2(size_bytes) - math.log2(preferred_size_bytes))
    return int(distance * 2)


def comparator_key(
    decision: Decision,
    profile: FormatProfile,
    now: datetime,
    preferred_size_bytes: int | None = None,
) -> tuple[int, int, int, int, int, int, str]:
    """Total-order sort key; lexicographically smaller = preferred (best first).

    ``profile`` is the target series' format profile — every candidate for one
    issue shares it, so it is passed once rather than carried per decision.
    """
    candidate = decision.candidate
    fmt = candidate_format(decision.parsed, candidate.title)
    return (
        -profile.rung(fmt),  # higher rung first
        candidate.indexer_priority,  # lower priority number first
        candidate.query_tier,  # lower (more specific) tier first
        _age_bucket(candidate.pub_date, now),  # fresher first
        _size_closeness_bucket(candidate.size_bytes, preferred_size_bytes),
        candidate.indexer_id,  # deterministic tiebreak (part 1)
        candidate.guid,  # deterministic tiebreak (part 2, globally unique per row)
    )


def order_decisions(
    decisions: list[Decision],
    profile: FormatProfile,
    now: datetime,
    preferred_size_bytes: int | None = None,
) -> list[Decision]:
    """Sort decisions best-first by the comparator chain (stable + total)."""
    return sorted(
        decisions,
        key=lambda d: comparator_key(d, profile, now, preferred_size_bytes),
    )


def best_decision(
    decisions: list[Decision],
    profile: FormatProfile,
    now: datetime,
    preferred_size_bytes: int | None = None,
) -> Decision | None:
    """The single top decision, or ``None`` for an empty input."""
    if not decisions:
        return None
    return min(
        decisions,
        key=lambda d: comparator_key(d, profile, now, preferred_size_bytes),
    )
