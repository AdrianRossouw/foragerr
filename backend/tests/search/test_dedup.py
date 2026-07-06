"""FRG-SRCH-010 — cross-indexer de-duplication."""

from __future__ import annotations

import pytest

from foragerr.search import DecisionEngine, deduplicate

from .builders import candidate, context, issue, series

ENGINE = DecisionEngine()


def _decide(title, **kw):
    s = series(1, "batman", issues=(issue(10, 5),))
    return ENGINE.evaluate(candidate(title, **kw), context(s))


@pytest.mark.req("FRG-SRCH-010")
def test_cross_indexer_keeps_higher_priority_indexer_copy():
    # Same release title + size on two indexers of differing priority.
    lo_pri = _decide(
        "Batman 005 (2016).cbz", guid="x", indexer_id=1, indexer_name="DogNZB",
        indexer_priority=1, size_bytes=30_000_100,
    )
    hi_num = _decide(
        "Batman 005 (2016).cbz", guid="y", indexer_id=2, indexer_name="NZBsu",
        indexer_priority=25, size_bytes=30_000_200,
    )
    result = deduplicate([hi_num, lo_pri])
    assert len(result) == 1
    assert result[0].candidate.indexer_id == 1  # lower priority number == higher priority


@pytest.mark.req("FRG-SRCH-010")
def test_per_indexer_guid_dedup_runs_first():
    a = _decide("Batman 005 (2016).cbz", guid="dup", indexer_id=1, size_bytes=30_000_000)
    b = _decide("Batman 005 (2016).cbz", guid="dup", indexer_id=1, size_bytes=30_000_000)
    result = deduplicate([a, b])
    assert len(result) == 1


@pytest.mark.req("FRG-SRCH-010")
def test_distinct_releases_are_not_collapsed():
    # Different guid AND different title/size key -> both kept.
    a = _decide("Batman 005 (2016).cbz", guid="a", indexer_id=1, size_bytes=30_000_000)
    b = _decide("Batman 006 (2016).cbz", guid="b", indexer_id=1, size_bytes=55_000_000)
    result = deduplicate([a, b])
    assert len(result) == 2


@pytest.mark.req("FRG-SRCH-010")
def test_same_title_different_size_bucket_not_collapsed():
    a = _decide("Batman 005 (2016).cbz", guid="a", indexer_id=1, size_bytes=30_000_000)
    b = _decide("Batman 005 (2016).cbz", guid="b", indexer_id=2, size_bytes=90_000_000)
    result = deduplicate([a, b])
    assert len(result) == 2


@pytest.mark.req("FRG-SRCH-010")
def test_near_identical_sizes_collapse_within_bucket():
    a = _decide("Batman 005 (2016).cbz", guid="a", indexer_id=1, indexer_priority=5, size_bytes=30_000_000)
    b = _decide("Batman 005 (2016).cbz", guid="b", indexer_id=2, indexer_priority=1, size_bytes=30_000_500)
    result = deduplicate([a, b])
    assert len(result) == 1
    assert result[0].candidate.indexer_id == 2  # higher priority survives


@pytest.mark.req("FRG-SRCH-010")
def test_fewest_rejections_preferred_over_priority():
    # Same normalized title/size on two indexers; the copy with fewer
    # rejections wins even if the other has higher indexer priority.
    s = series(1, "batman", issues=(issue(10, 5),))
    from foragerr.search import SearchTarget

    ctx_ok = context(s, target=SearchTarget(series_id=1, issue_id=10))
    ctx_bad = context(  # target mismatch -> extra rejection
        s, target=SearchTarget(series_id=1, issue_id=999)
    )
    clean = ENGINE.evaluate(
        candidate("Batman 005 (2016).cbz", guid="a", indexer_id=1, indexer_priority=25, size_bytes=30_000_000),
        ctx_ok,
    )
    rejected = ENGINE.evaluate(
        candidate("Batman 005 (2016).cbz", guid="b", indexer_id=2, indexer_priority=1, size_bytes=30_000_000),
        ctx_bad,
    )
    result = deduplicate([rejected, clean])
    assert len(result) == 1
    assert result[0].candidate.indexer_id == 1  # fewer rejections wins
