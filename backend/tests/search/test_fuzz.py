"""FRG-SRCH-001 / FRG-SRCH-002 — the engine never raises over hostile titles.

Seeded stdlib generation (no third-party property-testing dep, matching the
parser's test style): arbitrary Unicode, control characters, lone surrogates,
pathological punctuation runs, and huge inputs. Every candidate must yield a
structured Decision — approved or reasoned rejection — with zero unhandled
exceptions.
"""

from __future__ import annotations

import random

import pytest

from foragerr.releases import ReleaseCandidate
from foragerr.search import DecisionEngine, DecisionOutcome, SearchTarget

from .builders import candidate, context, issue, series

ENGINE = DecisionEngine()
SEED = 20260705

_ALPHABET = (
    "Batman 005 (2016) .cbz-#½∞[]()__ \t\n"
    "аниме 火 \x00\x01\ud800 " + "0123456789"
)


def _hostile_titles(n: int) -> list[str]:
    rng = random.Random(SEED)
    titles: list[str] = ["", " ", "\x00", "(((", "###", "\ud800\ud800", "." * 500]
    for _ in range(n):
        length = rng.randint(0, 60)
        titles.append("".join(rng.choice(_ALPHABET) for _ in range(length)))
    titles.append("A" * 200_000)  # oversized
    return titles


@pytest.mark.req("FRG-SRCH-002")
def test_engine_never_raises_over_hostile_titles():
    s = series(1, "batman", issues=(issue(10, 5),))
    ctx = context(s, target=SearchTarget(series_id=1, issue_id=10))
    for i, title in enumerate(_hostile_titles(500)):
        c = ReleaseCandidate(
            guid=f"g{i}", title=title, link="l", indexer_id=1, indexer_name="n",
            indexer_priority=1, query_tier=0, size_bytes=None, pub_date=None,
        )
        decision = ENGINE.evaluate(c, ctx)  # must not raise
        assert isinstance(decision.outcome, DecisionOutcome)
        # every non-approved decision carries at least one user-visible reason
        if not decision.approved:
            assert decision.reasons
            assert all(isinstance(r, str) for r in decision.reasons)


@pytest.mark.req("FRG-SRCH-001")
def test_engine_stable_no_context_defaults_to_empty_library():
    # Called with no context at all: still total, still never raises.
    d = ENGINE.evaluate(candidate("whatever 001"))
    assert d.outcome is DecisionOutcome.REJECTED  # unknown series, empty library
    assert d.reasons
