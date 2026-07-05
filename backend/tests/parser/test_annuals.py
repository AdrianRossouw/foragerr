"""FRG-IMP-015 — annuals and specials as structured classification."""

import pytest

from foragerr.parser import IssueClassification, parse


@pytest.mark.req("FRG-IMP-015")
def test_annual_with_numeric_issue_stays_numeric():
    for name in (
        "Batman Annual 02 (2017).cbz",
        "Batman.Annual.02.2017.digital.Glorith-HD.cbz",
    ):
        r = parse(name, reference_year=2026)
        assert r.series_name == "Batman", name  # marker removed from title
        assert r.issue.value == 2 and r.issue.display == "02", name
        assert r.year == 2017, name
        assert r.issue.classification is IssueClassification.ANNUAL, name
        # the issue number is never rewritten to the string 'Annual 02'
        assert "Annual" not in r.issue.display


@pytest.mark.req("FRG-IMP-015")
def test_year_annual_combined_forms():
    r = parse("Wolverine 1997 Annual.cbz", reference_year=2026)
    assert r.issue.classification is IssueClassification.ANNUAL
    assert r.issue.value == 1997  # year-as-issue
    assert r.year == 1997
    assert r.series_name == "Wolverine"


@pytest.mark.req("FRG-IMP-015")
def test_biannual_and_special_classifications():
    r = parse("Deadpool BiAnnual 01 (2014).cbz", reference_year=2026)
    assert r.issue.classification is IssueClassification.BIANNUAL
    assert (r.series_name, r.issue.value, r.year) == ("Deadpool", 1, 2014)
    r = parse("Gotham City Sirens Special 1 (2022).cbz", reference_year=2026)
    assert r.issue.classification is IssueClassification.SPECIAL
    assert (r.series_name, r.issue.value, r.year) == ("Gotham City Sirens", 1, 2022)
    # row 58 pinned: Summer is consumed with the special marker
    r = parse("Archie Summer Special 3 (1996).cbz", reference_year=2026)
    assert r.issue.classification is IssueClassification.SPECIAL
    assert (r.series_name, r.issue.value, r.year) == ("Archie", 3, 1996)


@pytest.mark.req("FRG-IMP-015")
def test_annual_and_volume_coexist():
    r = parse("Teen Titans v1 Annual 1 (1967).cbz", reference_year=2026)
    assert r.volume_ordinal == 1
    assert r.issue.classification is IssueClassification.ANNUAL
    assert r.issue.value == 1
    assert r.year == 1967
    assert r.series_name == "Teen Titans"


@pytest.mark.req("FRG-IMP-015")
def test_marker_words_at_title_start_stay_in_the_title():
    r = parse("Special Forces 01 (2008).cbz", reference_year=2026)
    assert r.series_name == "Special Forces"
    assert r.issue.classification is IssueClassification.REGULAR
