"""FRG-SRCH-006 — search-match specs: wrong-series/issue under q=-only search."""

from __future__ import annotations

import pytest

from foragerr.search import DecisionEngine, RejectionType, SearchTarget

from .builders import candidate, context, issue, series

ENGINE = DecisionEngine()


def _rej(decision, spec):
    return next((r for r in decision.rejections if r.spec == spec), None)


@pytest.mark.req("FRG-SRCH-006")
def test_wrong_series_rejected_under_q_only_search():
    # Searched Batman #5; a decodable Superman release comes back.
    batman = series(1, "batman", issues=(issue(10, 5),))
    superman = series(2, "superman", issues=(issue(20, 5),))
    ctx = context(batman, superman, target=SearchTarget(series_id=1, issue_id=10))
    d = ENGINE.evaluate(candidate("Superman 005 (2016)"), ctx)
    r = _rej(d, "search-match")
    assert r is not None and r.type is RejectionType.PERMANENT
    assert "Wrong series" in r.reason


@pytest.mark.req("FRG-SRCH-006")
def test_substring_series_collision_rejected_as_wrong_series():
    # Searched "Batman"; a tracked "Batman Beyond" release comes back. It maps
    # cleanly to Batman Beyond (a different tracked series) -> wrong series,
    # never grabbed for Batman.
    batman = series(1, "batman", issues=(issue(10, 5),))
    beyond = series(2, "batman beyond", issues=(issue(20, 5),))
    ctx = context(batman, beyond, target=SearchTarget(series_id=1, issue_id=10))
    d = ENGINE.evaluate(candidate("Batman Beyond 005 (2016)"), ctx)
    r = _rej(d, "search-match")
    assert r is not None
    assert "Wrong series" in r.reason
    assert d.mapped_series_id == 2  # correctly resolved to Beyond


@pytest.mark.req("FRG-SRCH-006")
def test_wrong_issue_rejected():
    batman = series(1, "batman", issues=(issue(10, 5), issue(11, 6)))
    ctx = context(batman, target=SearchTarget(series_id=1, issue_id=10))
    d = ENGINE.evaluate(candidate("Batman 006 (2016)"), ctx)
    r = _rej(d, "search-match")
    assert r is not None and "Wrong issue" in r.reason


@pytest.mark.req("FRG-SRCH-006")
def test_year_in_title_not_misread_as_issue():
    # Searching for issue 2016 (contrived) while the release is "#005 (2016)":
    # the year must NOT be read as issue 2016 -> the parsed issue is 5, which is
    # the wrong (searched) issue, so it is rejected rather than grabbed.
    batman = series(1, "batman", issues=(issue(10, 5), issue(99, 2016)))
    ctx = context(batman, target=SearchTarget(series_id=1, issue_id=99))
    d = ENGINE.evaluate(candidate("Batman (2016) 005"), ctx)
    r = _rej(d, "search-match")
    assert r is not None and "Wrong issue" in r.reason
    assert d.mapped_issue_id == 10  # resolved to issue 5, not year 2016


@pytest.mark.req("FRG-SRCH-006")
def test_correct_series_and_issue_passes():
    batman = series(1, "batman", issues=(issue(10, 5),))
    ctx = context(batman, target=SearchTarget(series_id=1, issue_id=10))
    d = ENGINE.evaluate(candidate("Batman 005 (2016) (cbz)"), ctx)
    assert _rej(d, "search-match") is None
    assert d.approved


@pytest.mark.req("FRG-SRCH-006")
def test_search_match_inert_without_target():
    # Pure mapping path (no target): search-match never fires.
    batman = series(1, "batman", issues=(issue(10, 5),))
    d = ENGINE.evaluate(candidate("Batman 005 (2016) (cbz)"), context(batman))
    assert _rej(d, "search-match") is None
