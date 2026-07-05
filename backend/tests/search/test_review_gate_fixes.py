"""Review-gate regression tests for the decision engine (change 4).

- C5 (FRG-IDX-009): a per-indexer retention override wins over the global
  retention for that indexer's own candidates.
- C13 (FRG-SRCH-004): an unknown container format is unjudgeable pre-download,
  so the upgrade spec must PASS it even when a file already exists — and never
  render a bare ``'None'`` in a rejection reason.
"""

from __future__ import annotations

import pytest

from foragerr.search import (
    DecisionEngine,
    EngineConfig,
    ExistingFile,
    RejectionType,
    SearchTarget,
)

from .builders import candidate, context, issue, series

ENGINE = DecisionEngine()


def _target_ctx(*serieses, **kw):
    return context(*serieses, target=SearchTarget(series_id=1, issue_id=10), **kw)


def _rej(decision, spec):
    return next((r for r in decision.rejections if r.spec == spec), None)


@pytest.mark.req("FRG-IDX-009")
def test_per_indexer_retention_override_beats_global():
    s = series(1, "batman", issues=(issue(10, 5),))
    # Indexer 7 carries a generous retention override; indexer 9 has none and
    # so falls back to the global 1000-day limit.
    cfg = EngineConfig(retention_days=1000, retention_by_indexer={7: 5000})

    within = candidate(
        "Batman 005 (2016).cbz", indexer_id=7, age_hours=24 * 2000
    )
    d_within = ENGINE.evaluate(within, _target_ctx(s, config=cfg))
    assert _rej(d_within, "retention") is None, (
        "a candidate older than global but within its indexer's override must "
        "not be rejected"
    )

    beyond = candidate(
        "Batman 005 (2016).cbz", guid="g2", indexer_id=9, age_hours=24 * 2000
    )
    d_beyond = ENGINE.evaluate(beyond, _target_ctx(s, config=cfg))
    r = _rej(d_beyond, "retention")
    assert r is not None and r.type is RejectionType.PERMANENT, (
        "a candidate from a no-override indexer beyond the global limit is "
        "still rejected"
    )


@pytest.mark.req("FRG-SRCH-004")
def test_unknown_format_upgrade_passes_and_never_renders_none():
    existing = (ExistingFile(format="cbz", size_bytes=30_000_000),)
    s = series(1, "batman", issues=(issue(10, 5, files=existing),))
    # No container token in the title -> resolved format is unknown (None). The
    # upgrade spec must not reject it (import re-verifies), consistent with the
    # format-allowed spec permitting unknowns.
    d = ENGINE.evaluate(candidate("Batman 005 (2016)"), _target_ctx(s))
    assert d.fmt is None
    assert _rej(d, "upgrade-allowed") is None
    # No rejection reason ever interpolates a bare 'None'.
    assert all("'None'" not in r.reason for r in d.rejections)
