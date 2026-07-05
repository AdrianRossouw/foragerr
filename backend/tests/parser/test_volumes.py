"""FRG-IMP-012 — volume designators including volume-years."""

import pytest

from foragerr.parser import parse


@pytest.mark.req("FRG-IMP-012")
def test_all_ordinal_spellings_converge():
    for name in (
        "Batman v2 015 (2012).cbz",
        "Batman V2 015 (2012).cbz",
        "Batman v02 015 (2012).cbz",
        "Batman vol 2 015 (2012).cbz",
        "Batman vol.2 015 (2012).cbz",
        "Batman vol. 2 015 (2012).cbz",
        "Batman Vol. 2 015 (2012).cbz",
        "Batman volume 2 015 (2012).cbz",
        "Batman volume2 015 (2012).cbz",
    ):
        r = parse(name, reference_year=2026)
        assert r.volume_ordinal == 2, name  # a typed field, not a 'v2' string
        assert r.volume_year is None, name
        assert r.issue.value == 15, name
        assert r.year == 2012, name
        assert r.series_name == "Batman", name


@pytest.mark.req("FRG-IMP-012")
def test_roman_numeral_volumes_captured_not_discarded():
    r = parse("Sandman Vol III 05 (1991).cbz", reference_year=2026)
    assert r.volume_ordinal == 3
    assert r.issue.value == 5
    assert r.year == 1991
    # no volume keyword: mid-title roman numerals stay in the title
    r = parse("Star Wars Legacy II 03 (2013).cbz", reference_year=2026)
    assert r.series_name == "Star Wars Legacy II"
    assert r.volume_ordinal is None
    assert r.issue.value == 3


@pytest.mark.req("FRG-IMP-012")
def test_volume_years_and_year_ranges_are_distinct_fields():
    r = parse("Justice League v2017 021 (2018).cbz", reference_year=2026)
    assert r.volume_year == 2017
    assert r.volume_ordinal is None
    assert r.issue.value == 21
    assert r.year == 2018
    r = parse("Casper (1953-) 001.cbz", reference_year=2026)
    assert r.volume_year == 1953  # series start year, not a cover date
    assert r.year is None
    assert r.issue.value == 1
    r = parse("Casper (1953-1959) 001.cbz", reference_year=2026)
    assert r.volume_year == 1953


@pytest.mark.req("FRG-IMP-012")
def test_part_n_is_not_a_volume():
    r = parse("Astonishing X-Men Part 2 (2018).cbz", reference_year=2026)
    assert r.volume_ordinal is None
    assert r.volume_year is None
    # Part N is an issue/chapter cue (deliberate divergence from Mylar)
    assert r.issue.value == 2
    assert r.series_name == "Astonishing X-Men"
