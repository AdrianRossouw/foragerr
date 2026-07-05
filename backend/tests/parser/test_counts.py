"""FRG-IMP-011 — mini-series counts and cover/page-tag stripping."""

from fractions import Fraction

import pytest

from foragerr.parser import parse


@pytest.mark.req("FRG-IMP-011")
def test_of_n_anchors_the_issue_over_competitors():
    r = parse("Batman 39 (of 52) (2017).cbz", reference_year=2026)
    assert r.issue.value == 39
    assert r.miniseries_total == 52
    r = parse("Kick-Ass 3 01 (of 08) (2013).cbz", reference_year=2026)
    assert r.series_name == "Kick-Ass 3"  # the competing 3 stays in the title
    assert r.issue.value == 1
    assert r.miniseries_total == 8


@pytest.mark.req("FRG-IMP-011")
def test_bare_of_form_and_decimal_totals():
    r = parse("Kick-Ass 01 of 08 (2013).cbz", reference_year=2026)
    assert r.issue.value == 1
    assert r.miniseries_total == 8
    r = parse("Empowered 01 (of 7.3) (2015).cbz", reference_year=2026)
    assert r.issue.value == 1
    assert r.miniseries_total == Fraction("7.3")
    assert r.year == 2015


@pytest.mark.req("FRG-IMP-011")
def test_cover_counts_and_page_tags_never_issues():
    r = parse("Descender 011 (2 covers) (2016).cbz", reference_year=2026)
    assert r.issue.value == 11
    r = parse("Saga 55 (2018) (digital) (36p ctc).cbz", reference_year=2026)
    assert r.issue.value == 55
    r = parse("Lazarus 01 (2013) (1440px).cbz", reference_year=2026)
    assert r.issue.value == 1
    for name in (
        "Descender 011 (2 covers) (2016).cbz",
        "Saga 55 (2018) (digital) (36p ctc).cbz",
        "Lazarus 01 (2013) (1440px).cbz",
    ):
        r = parse(name, reference_year=2026)
        for token in ("covers", "ctc", "px", "1440", "36p"):
            assert token not in (r.series_name or "")
            assert token not in (r.issue.display if r.issue else "")
        assert r.volume_ordinal is None and r.volume_year is None


@pytest.mark.req("FRG-IMP-011")
def test_of_infinity_is_not_a_count_marker():
    r = parse("Series 03 (of infinity) (2018).cbz", reference_year=2026)
    assert r.issue.value == 3
    assert r.miniseries_total is None
    assert ("generic", "of infinity") in {(a.kind.value, a.text) for a in r.annotations}
    assert r.scan_group is None
