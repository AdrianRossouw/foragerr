"""FRG-IMP-008 — decimal, negative, and Unicode-fraction issue numbers."""

from fractions import Fraction

import pytest

from foragerr.parser import parse


@pytest.mark.req("FRG-IMP-008")
def test_decimals_normalize_to_value_plus_display():
    cases = {
        "Invincible 015.5 (2005).cbz": (Fraction("15.5"), "015.5"),
        "Elephantmen 20.5 (2009).cbz": (Fraction("20.5"), "20.5"),
        "Gold Digger 0.5 (1997).cbr": (Fraction("0.5"), "0.5"),
    }
    for name, (value, display) in cases.items():
        r = parse(name, reference_year=2026)
        assert r.issue.value == value, name
        assert r.issue.display == display, name
        assert r.issue.suffix is None


@pytest.mark.req("FRG-IMP-008")
def test_negative_issue_is_typed_value():
    r = parse("Deadpool -1 (1997).cbz", reference_year=2026)
    assert r.issue.value == -1
    assert r.issue.display == "-1"
    assert r.series_name == "Deadpool"
    assert r.year == 1997


@pytest.mark.req("FRG-IMP-008")
def test_unicode_fractions_standalone_and_composite():
    r = parse("Uncanny X-Men ½ (1999).cbz", reference_year=2026)
    assert r.issue.value == Fraction(1, 2)
    assert r.issue.display == "½"
    r = parse("Batman 000.0000½ (2015).cbz", reference_year=2026)
    assert r.issue.value == Fraction(1, 2)
    assert r.issue.display == "000.0000½"
    # quarter and three-quarter glyphs too
    assert parse("X ¼ (2000).cbz", reference_year=2026).issue.value == Fraction(1, 4)
    assert parse("X ¾ (2000).cbz", reference_year=2026).issue.value == Fraction(3, 4)


@pytest.mark.req("FRG-IMP-008")
def test_infinity_words_never_become_infinite_issues():
    r = parse("Scott Pilgrim & The Infinite Sadness v3 (2006).cbz", reference_year=2026)
    assert r.issue is None
    assert "Infinite" in r.series_name
    r = parse("Avengers Infinity 2021 001 (2021).cbz", reference_year=2026)
    assert r.issue.value == 1
    assert r.issue.is_infinity is False
    assert "Infinity" in r.series_name
    # only the literal glyph produces an infinity-classified record
    r = parse("Uncanny X-Men ∞ (2015).cbz", reference_year=2026)
    assert r.issue.is_infinity is True
    assert r.issue.value is None
    assert r.issue.display == "∞"
