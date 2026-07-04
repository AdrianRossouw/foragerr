"""FRG-IMP-016 — booktype detection as a distinct enum."""

import pytest

from foragerr.parser import Booktype, parse


@pytest.mark.req("FRG-IMP-016")
def test_tpb_forms_interpret_trailing_number_as_volume():
    r = parse("Saga TPB v01 (2013).cbz", reference_year=2026)
    assert r.booktype is Booktype.TPB
    assert r.volume_ordinal == 1
    r = parse("Monstress Vol. 06 (2021) (Digital) TPB.cbz", reference_year=2026)
    assert r.booktype is Booktype.TPB
    assert r.volume_ordinal == 6
    # trailing number becomes the volume when no designator is present
    r = parse("Saga TPB 02 (2014).cbz", reference_year=2026)
    assert r.booktype is Booktype.TPB
    assert r.volume_ordinal == 2
    assert r.issue is None
    # explicit trade with no volume: the only fabricated v1
    r = parse("East of West TPB (2014).cbz", reference_year=2026)
    assert r.booktype is Booktype.TPB
    assert r.volume_ordinal == 1


@pytest.mark.req("FRG-IMP-016")
def test_multi_word_forms_match_across_tokens():
    r = parse("Pride of Baghdad Graphic Novel (2006).cbz", reference_year=2026)
    assert r.booktype is Booktype.GN  # fixes Mylar's unreachable two-word match
    assert r.series_name == "Pride of Baghdad"
    r = parse("Kill or be Killed v1 (2017) (Digital TPB).cbz", reference_year=2026)
    assert r.booktype is Booktype.TPB
    assert r.volume_ordinal == 1
    assert r.year == 2017
    r = parse("Essex County Trade Paperback (2009).cbz", reference_year=2026)
    assert r.booktype is Booktype.TPB
    r = parse("Maus Hardcover (1991).cbz", reference_year=2026)
    assert r.booktype is Booktype.HC


@pytest.mark.req("FRG-IMP-016")
def test_hc_gn_abbreviations_and_no_union_value():
    r = parse("Watchmen HC (1988).cbz", reference_year=2026)
    assert r.booktype is Booktype.HC
    r = parse("Blacksad GN (2010).cbz", reference_year=2026)
    assert r.booktype is Booktype.GN
    # the enum has no TPB/GN/HC/One-Shot-style union member
    members = {m.value for m in Booktype}
    assert members == {"issue", "TPB", "GN", "HC", "one-shot"}
    assert not any("/" in v for v in members)


@pytest.mark.req("FRG-IMP-016")
def test_default_booktype_is_issue_with_no_fabricated_volume():
    r = parse("Batman 404 (1987).cbz", reference_year=2026)
    assert r.booktype is Booktype.ISSUE
    assert r.volume_ordinal is None
    assert r.volume_year is None
