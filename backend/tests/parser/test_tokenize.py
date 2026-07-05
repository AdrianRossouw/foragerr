"""FRG-IMP-004 — tokenization and separator handling."""

import pytest

from foragerr.parser import parse
from foragerr.parser.tokenize import TokenKind, is_dot_dominant, tokenize


@pytest.mark.req("FRG-IMP-004")
def test_underscores_and_commas_parse_identically_to_spaces():
    reference = parse("Batman 404 (1987).cbz", reference_year=2026).to_json()
    assert parse("Batman_404_(1987).cbz", reference_year=2026).to_json() == reference
    assert parse("Batman,404,(1987).cbz", reference_year=2026).to_json() == reference


@pytest.mark.req("FRG-IMP-004")
@pytest.mark.req("FRG-IMP-017")
def test_underscore_mangled_name_with_trailing_annotations():
    r = parse("Captain_Atom_007__2012___digital-TheGroup_.cbr", reference_year=2026)
    assert r.series_name == "Captain Atom"
    assert r.issue.value == 7 and r.issue.display == "007"
    assert r.year == 2012
    assert ("edition", "digital") in {(a.kind.value, a.text) for a in r.annotations}
    assert r.scan_group == "TheGroup"


@pytest.mark.req("FRG-IMP-004")
def test_dots_split_only_when_dot_dominant():
    r = parse("Amazing.Spider-Man.798.2018.Digital.Empire.cbr", reference_year=2026)
    assert r.series_name == "Amazing Spider-Man"
    assert r.issue.value == 798
    assert r.year == 2018

    r = parse("Batman Beyond 2.0 015 (2013).cbz", reference_year=2026)
    assert r.series_name == "Batman Beyond 2.0"
    assert r.issue.value == 15
    assert r.year == 2013

    assert is_dot_dominant("Amazing.Spider-Man.798.2018.Digital.Empire")
    assert not is_dot_dominant("Batman Beyond 2.0 015 (2013)")


@pytest.mark.req("FRG-IMP-004")
def test_paren_and_bracket_groups_are_atomic_tokens():
    tokens = tokenize("Saga 55 (2018) (digital) (36p ctc)")
    groups = [t for t in tokens if t.kind is TokenKind.GROUP_PAREN]
    assert [g.inner for g in groups] == ["2018", "digital", "36p ctc"]
    r = parse("Saga 55 (2018) (digital) (36p ctc).cbz", reference_year=2026)
    assert r.series_name == "Saga"
    assert r.issue.value == 55
    assert r.year == 2018
    # none of the inner words leak into title or issue
    assert "digital" not in r.series_name and "ctc" not in r.series_name


@pytest.mark.req("FRG-IMP-004")
def test_repeated_tokens_cannot_corrupt_positions():
    r = parse("Batman 66 66 (2016).cbz", reference_year=2026)
    assert r.series_name == "Batman 66"
    assert r.issue.value == 66
    assert r.year == 2016
    # index-stable bookkeeping: tokens carry distinct stream indices
    tokens = tokenize("Batman 66 66 (2016)")
    indices = [t.index for t in tokens]
    assert indices == sorted(set(indices))


@pytest.mark.req("FRG-IMP-004")
def test_unbalanced_groups_never_crash():
    for name in ("Batman (unclosed 404", "Batman ]404[ (1987)", "((((", "))))"):
        assert tokenize(name) is not None
        assert parse(name + ".cbz", reference_year=2026) is not None
