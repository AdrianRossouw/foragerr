"""FRG-IMP-019 — series title output and alternate title splits."""

import pytest

from foragerr.parser import matching_key, parse


@pytest.mark.req("FRG-IMP-019")
def test_hyphen_delimited_subtitle_produces_alternate_split():
    r = parse("Batman - The Long Halloween 05 (1997).cbz", reference_year=2026)
    assert r.series_name == "Batman - The Long Halloween"
    assert r.issue.value == 5
    assert r.year == 1997
    assert r.alt_series == "Batman"
    assert r.alt_issue_title == "The Long Halloween"


@pytest.mark.req("FRG-IMP-019")
def test_trailing_issue_title_after_the_issue_number():
    r = parse("Daredevil 600 - Mayor Fisk (2018).cbz", reference_year=2026)
    assert r.series_name == "Daredevil"
    assert r.issue.value == 600
    assert r.year == 2018
    assert r.alt_issue_title == "Mayor Fisk"


@pytest.mark.req("FRG-IMP-019")
def test_hyphenated_title_words_survive_uncorrupted():
    r = parse("X-23 012 (2011).cbz", reference_year=2026)
    assert r.series_name == "X-23"
    assert r.alt_series is None and r.alt_issue_title is None
    assert r.issue.value == 12
    r = parse("Star Wars Legacy II 03 (2013).cbz", reference_year=2026)
    assert r.series_name == "Star Wars Legacy II"
    assert r.issue.value == 3


@pytest.mark.req("FRG-IMP-019")
@pytest.mark.req("FRG-IMP-005")
def test_raw_title_and_folded_matching_key_both_returned():
    r = parse("Amazing.Spider-Man.798.2018.Digital.Empire.cbr", reference_year=2026)
    assert r.series_name == "Amazing Spider-Man"  # original casing preserved
    assert r.matching_key == matching_key("Amazing Spider-Man")
    assert r.matching_key != r.series_name
