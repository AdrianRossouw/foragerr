"""FRG-IMP-014 — year-equals-issue one-shot disambiguation."""

import pytest

from foragerr.parser import Booktype, IssueClassification, parse


@pytest.mark.req("FRG-IMP-014")
def test_bare_year_equals_issue_folds_into_title_as_one_shot():
    r = parse("Superman Smashes the Klan 2020 (2020).cbz", reference_year=2026)
    assert r.series_name == "Superman Smashes the Klan 2020"
    assert r.issue is None  # never issue #2020
    assert r.year == 2020
    assert r.booktype is Booktype.ONE_SHOT


@pytest.mark.req("FRG-IMP-014")
@pytest.mark.req("FRG-IMP-015")
def test_annual_marker_beats_one_shot_reclassification():
    r = parse("Batman Annual 2021 (2021).cbz", reference_year=2026)
    assert r.issue is not None
    assert r.issue.value == 2021  # year-as-issue
    assert r.issue.classification is IssueClassification.ANNUAL
    assert r.series_name == "Batman"
    assert r.year == 2021
    assert r.booktype is Booktype.ISSUE


@pytest.mark.req("FRG-IMP-014")
def test_distinct_issue_candidate_disables_the_rule():
    r = parse("Batman 2020 005 (2020).cbz", reference_year=2026)
    assert r.issue.value == 5
    assert r.year == 2020
    assert r.series_name == "Batman 2020"
    assert r.booktype is Booktype.ISSUE
