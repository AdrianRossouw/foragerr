"""FRG-SRCH-007 — prioritization comparator: chain order, bucketing, total order."""

from __future__ import annotations

import random

import pytest

from foragerr.search import (
    DecisionEngine,
    FormatProfile,
    best_decision,
    comparator_key,
    order_decisions,
)

from .builders import NOW, candidate, context, issue, series

ENGINE = DecisionEngine()
PROFILE = FormatProfile(formats=("pdf", "cbr", "cbz"), cutoff="cbz")


def _decide(title, **kw):
    # Evaluate against a permissive single-series context so the candidate is
    # approved; the comparator only ever orders approved decisions.
    s = series(1, "batman", issues=(issue(10, 5),), profile=PROFILE)
    return ENGINE.evaluate(candidate(title, **kw), context(s))


@pytest.mark.req("FRG-SRCH-007")
def test_format_rung_dominates_indexer_priority():
    # cbz from a low-priority indexer (25) vs cbr from a high-priority one (1);
    # under a cbz-first profile the cbz wins because format rung is compared
    # before indexer priority.
    cbz_low = _decide("Batman 005 (2016).cbz", guid="a", indexer_id=2, indexer_priority=25)
    cbr_high = _decide("Batman 005 (2016).cbr", guid="b", indexer_id=1, indexer_priority=1)
    ordered = order_decisions([cbr_high, cbz_low], PROFILE, NOW)
    assert ordered[0] is cbz_low


@pytest.mark.req("FRG-SRCH-007")
def test_indexer_priority_breaks_format_tie():
    lo = _decide("Batman 005 (2016).cbz", guid="a", indexer_id=1, indexer_priority=1)
    hi = _decide("Batman 005 (2016).cbz", guid="b", indexer_id=2, indexer_priority=9)
    ordered = order_decisions([hi, lo], PROFILE, NOW)
    assert ordered[0] is lo  # lower priority number wins


@pytest.mark.req("FRG-SRCH-007")
def test_query_tier_breaks_tie_after_priority():
    specific = _decide("Batman 005 (2016).cbz", guid="a", query_tier=0, indexer_id=1)
    broad = _decide("Batman 005 (2016).cbz", guid="b", query_tier=3, indexer_id=1)
    ordered = order_decisions([broad, specific], PROFILE, NOW)
    assert ordered[0] is specific  # lower (more specific) tier wins


@pytest.mark.req("FRG-SRCH-007")
def test_bucketed_age_breaks_tie_and_fresh_wins():
    fresh = _decide("Batman 005 (2016).cbz", guid="a", age_hours=1, indexer_id=1)
    old = _decide("Batman 005 (2016).cbz", guid="b", age_hours=24 * 30, indexer_id=1)
    ordered = order_decisions([old, fresh], PROFILE, NOW)
    assert ordered[0] is fresh


@pytest.mark.req("FRG-SRCH-007")
def test_bucketing_prevents_trivial_age_delta_from_dominating():
    # Two candidates a few minutes apart fall in the same log bucket -> the age
    # comparator ties and ordering falls through to the guid tiebreak, not the
    # trivial delta.
    a = _decide("Batman 005 (2016).cbz", guid="a", age_hours=10.0, indexer_id=1)
    b = _decide("Batman 005 (2016).cbz", guid="b", age_hours=10.05, indexer_id=1)
    ka = comparator_key(a, PROFILE, NOW)
    kb = comparator_key(b, PROFILE, NOW)
    # identical up to (and including) the age bucket
    assert ka[:4] == kb[:4]


@pytest.mark.req("FRG-SRCH-007")
def test_size_closeness_only_applies_with_a_preferred_size():
    near = _decide("Batman 005 (2016).cbz", guid="a", size_bytes=30_000_000, indexer_id=1)
    far = _decide("Batman 005 (2016).cbz", guid="b", size_bytes=300_000_000, indexer_id=1)
    # Without a preferred size the closeness bucket ties (M1 default).
    assert comparator_key(near, PROFILE, NOW)[4] == comparator_key(far, PROFILE, NOW)[4]
    # With one, the nearer candidate sorts first.
    ordered = order_decisions([far, near], PROFILE, NOW, preferred_size_bytes=30_000_000)
    assert ordered[0] is near


@pytest.mark.req("FRG-SRCH-007")
def test_total_deterministic_order_independent_of_permutation():
    rng = random.Random(20260705)
    formats = ["pdf", "cbr", "cbz"]
    decisions = []
    for i in range(40):
        decisions.append(
            _decide(
                f"Batman 005 (2016).{rng.choice(formats)}",
                guid=f"g{i:03d}",
                indexer_id=rng.randint(1, 3),
                indexer_priority=rng.randint(1, 5),
                query_tier=rng.randint(0, 3),
                age_hours=rng.choice([1, 10, 100, 1000]),
                size_bytes=rng.choice([20_000_000, 30_000_000, 90_000_000]),
            )
        )
    baseline = [d.candidate.guid for d in order_decisions(decisions, PROFILE, NOW)]
    for _ in range(20):
        shuffled = decisions[:]
        rng.shuffle(shuffled)
        result = [d.candidate.guid for d in order_decisions(shuffled, PROFILE, NOW)]
        assert result == baseline
    # keys are strictly ordered: no two distinct candidates share a full key
    keys = [comparator_key(d, PROFILE, NOW) for d in decisions]
    assert len(set(keys)) == len(keys)


@pytest.mark.req("FRG-SRCH-007")
def test_best_decision_matches_first_of_ordered():
    decisions = [
        _decide("Batman 005 (2016).cbr", guid="a", indexer_id=1),
        _decide("Batman 005 (2016).cbz", guid="b", indexer_id=2),
    ]
    assert best_decision(decisions, PROFILE, NOW) is order_decisions(decisions, PROFILE, NOW)[0]
    assert best_decision([], PROFILE, NOW) is None
