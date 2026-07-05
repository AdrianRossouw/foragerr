"""FRG-IMP-005 — Unicode-native handling, single-sourced normalization."""

import pathlib

import pytest

from foragerr import parser as parser_module
from foragerr.parser import matching_key, parse
from foragerr.parser.normalize import matching_key as normalize_matching_key

SRC = pathlib.Path(parser_module.__file__).parent


@pytest.mark.req("FRG-IMP-005")
def test_unicode_dashes_treated_as_title_delimiters():
    em = parse("Batman — The Long Halloween 05 (1997).cbz", reference_year=2026)
    ascii_ = parse("Batman - The Long Halloween 05 (1997).cbz", reference_year=2026)
    assert em.issue.value == 5 and em.year == 1997
    assert em.alt_series == "Batman"
    assert em.alt_issue_title == "The Long Halloween"
    assert ascii_.alt_series == em.alt_series
    # raw series_name preserves the original glyph
    assert "—" in em.series_name
    assert em.matching_key == ascii_.matching_key


@pytest.mark.req("FRG-IMP-005")
@pytest.mark.req("FRG-IMP-009")
def test_curly_apostrophe_matches_vocabulary():
    r = parse("Gideon Falls Director’s Cut 1 (2018).cbz", reference_year=2026)
    assert r.series_name == "Gideon Falls"
    assert r.issue.value == 1
    kinds = {(a.kind.value, a.text) for a in r.annotations}
    assert ("edition", "Director’s Cut") in kinds  # original glyph preserved


@pytest.mark.req("FRG-IMP-005")
def test_fraction_glyphs_native_no_sentinel_pass():
    r = parse("Uncanny X-Men ½ (1999).cbz", reference_year=2026)
    assert r.issue.display == "½"
    assert "XCV" not in r.to_json()


@pytest.mark.req("FRG-IMP-005")
def test_ampersand_and_matching_key_from_single_function():
    r = parse("Scott Pilgrim & The Infinite Sadness v3 (2006).cbz", reference_year=2026)
    assert r.series_name == "Scott Pilgrim & The Infinite Sadness"  # no f11 sentinel
    # the folded key comes from the one shared normalization function
    assert r.matching_key == matching_key(r.series_name)
    assert matching_key is normalize_matching_key
    # punctuation folded, articles handled, case/separators collapsed
    assert r.matching_key == "scott pilgrim infinite sadness"


@pytest.mark.req("FRG-IMP-005")
def test_no_second_folding_implementation_exists():
    count = sum(
        s.read_text().count("def matching_key(") for s in SRC.rglob("*.py")
    )
    assert count == 1


@pytest.mark.req("FRG-IMP-005")
def test_matching_key_is_nfkd_aware_and_stable():
    # composed vs decomposed forms fold to the same key
    composed = "Caf\u00e9 Racer"  # e-acute as a single code point
    decomposed = "Cafe\u0301 Racer"  # e + combining acute
    assert matching_key(composed) == matching_key(decomposed)
    assert matching_key("The Batman") == matching_key("BATMAN")
