"""FRG-IMP-009 — alphanumeric issue suffixes and named issues."""

import pytest

from foragerr.parser import DEFAULT_OPTIONS, parse


@pytest.mark.req("FRG-IMP-009")
def test_glued_space_and_dotted_suffix_forms():
    cases = {
        "Wolverine 027AU (2013).cbz": (27, "AU", "027AU"),
        "Age of Ultron 10 AI (2013).cbz": (10, "AI", "10 AI"),
        "Uncanny Avengers 008.NOW (2013).cbz": (8, "NOW", "008.NOW"),
        "Avengers 024.NOW! (2014).cbz": (24, "NOW", "024.NOW"),
        "Mighty Avengers 004.INH (2013).cbz": (4, "INH", "004.INH"),
        "Spider-Verse 001.MU (2015).cbz": (1, "MU", "001.MU"),
        "Fantastic Four 600-X (2012).cbz": (600, "X", "600-X"),
    }
    for name, (value, suffix, display) in cases.items():
        r = parse(name, reference_year=2026)
        assert r.issue.value == value, name
        assert r.issue.suffix == suffix, name
        assert r.issue.display == display, name


@pytest.mark.req("FRG-IMP-009")
def test_pure_alpha_issue_names_require_hash_anchor():
    r = parse("Secret Wars #Alpha (2015).cbz", reference_year=2026)
    assert r.series_name == "Secret Wars"
    assert r.issue is not None and r.issue.name == "Alpha"
    assert r.issue.value is None
    # the unanchored variant keeps Alpha in the series title
    r = parse("Secret Wars Alpha (2015).cbz", reference_year=2026)
    assert r.series_name == "Secret Wars Alpha"
    assert r.issue is None


@pytest.mark.req("FRG-IMP-009")
def test_single_letter_and_vocabulary_word_guards():
    r = parse("Justice League 30 Cover B (2019).cbz", reference_year=2026)
    assert r.issue.value == 30
    assert r.issue.suffix is None  # never issue `30 B`
    assert ("cover-variant", "Cover B") in {
        (a.kind.value, a.text) for a in r.annotations
    }
    r = parse("Batman Black and White 03 (2013).cbz", reference_year=2026)
    assert r.series_name == "Batman Black and White"
    assert r.issue.value == 3
    # glued single letters fire only in the glued-to-digits position
    r = parse("Amazing Spider-Man 015A (2014).cbz", reference_year=2026)
    assert (r.issue.value, r.issue.suffix) == (15, "A")


@pytest.mark.req("FRG-IMP-009")
def test_suffix_vocabulary_is_configurable_data():
    r = parse("Gideon Falls Director's Cut 1 (2018).cbz", reference_year=2026)
    assert r.issue.value == 1
    assert r.issue.suffix is None
    assert ("edition", "Director's Cut") in {
        (a.kind.value, a.text) for a in r.annotations
    }
    # data-only vocabulary extension, no code change
    default = parse("Series 05 XYZ (2020).cbz", reference_year=2026)
    assert default.issue.suffix is None
    assert "XYZ" in (default.alt_issue_title or "") + (default.series_name or "")
    extended = parse(
        "Series 05 XYZ (2020).cbz",
        reference_year=2026,
        options=DEFAULT_OPTIONS.with_suffixes("XYZ"),
    )
    assert extended.issue.value == 5
    assert extended.issue.suffix == "XYZ"
