"""FRG-IMP-007 — plain/# issue numbers, leading-title guard, selection pins."""

import pytest

from foragerr.parser import parse


@pytest.mark.req("FRG-IMP-007")
def test_plain_and_anchored_integers_with_padding():
    r = parse("Batman 404 (1987).cbz", reference_year=2026)
    assert r.issue.value == 404 and r.issue.display == "404"
    r = parse("Batman #404 (1987).cbr", reference_year=2026)
    assert r.issue.value == 404 and r.issue.display == "404"
    r = parse("SWAMP THING # 028.cbr", reference_year=2026)
    assert r.series_name == "SWAMP THING"
    assert r.issue.value == 28
    assert r.issue.display == "028"  # zero-padding retained in display


@pytest.mark.req("FRG-IMP-007")
def test_leading_numeric_tokens_stay_in_the_title():
    cases = {
        "100 Bullets 050 (2003).cbz": ("100 Bullets", 50),
        "52 018 (2006).cbz": ("52", 18),
        "2000AD prog 2205 (2020).cbz": ("2000AD prog", 2205),
        "4001 A.D. 001 (2016).cbz": ("4001 A.D.", 1),
    }
    for name, (series, issue) in cases.items():
        r = parse(name, reference_year=2026)
        assert r.series_name == series, name
        assert r.issue.value == issue, name


@pytest.mark.req("FRG-IMP-007")
def test_matched_tokens_own_hash_governs_not_first_hash():
    r = parse("Beach Blanket Bingo #3 Special #005 (2001).cbz", reference_year=2026)
    assert r.issue.value == 5
    assert r.issue.display == "005"


@pytest.mark.req("FRG-IMP-007")
@pytest.mark.req("FRG-IMP-019")
def test_dash_demotion_and_rightmost_survivor():
    r = parse("Daredevil 600 - Mayor Fisk (2018).cbz", reference_year=2026)
    assert r.issue.value == 600
    assert r.series_name == "Daredevil"
    assert r.alt_issue_title == "Mayor Fisk"
    # numbers inside a post-dash subtitle are demoted
    r = parse("Daredevil 600 - 12 Angry Men (2018).cbz", reference_year=2026)
    assert r.issue.value == 600

    # year-position candidates are excluded from issue selection
    r = parse("Amazing Mary Jane (2019) 002.cbr", reference_year=2026)
    assert r.issue.value == 2 and r.year == 2019


@pytest.mark.req("FRG-IMP-007")
def test_rightmost_survivor_between_plain_candidates():
    r = parse("Batman Beyond 2.0 015 (2013).cbz", reference_year=2026)
    assert r.issue.value == 15
    r = parse("Batman 2020 005 (2020).cbz", reference_year=2026)
    assert r.issue.value == 5 and r.series_name == "Batman 2020"


@pytest.mark.req("FRG-IMP-007")
def test_anchored_at_title_start_is_still_an_issue():
    # the leading-title guard applies to unanchored numbers only
    r = parse("100 Bullets 050 (2003).cbz", reference_year=2026)
    assert r.issue.value == 50
    r = parse("Batman #1 (2011).cbz", reference_year=2026)
    assert r.issue.value == 1
