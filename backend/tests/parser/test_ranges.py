"""FRG-IMP-010 — issue ranges: structured or diagnostic, never collapsed."""

import pathlib

import pytest

from foragerr import parser as parser_module
from foragerr.parser import parse

SRC = pathlib.Path(parser_module.__file__).parent


@pytest.mark.req("FRG-IMP-010")
def test_hyphen_range_detected_never_silently_collapsed():
    r = parse("Preacher 01-66 Complete.cbz", reference_year=2026)
    assert r.issue is None  # neither endpoint silently reported alone
    assert r.issue_range is not None
    assert r.issue_range.start == 1
    assert r.issue_range.end == 66


@pytest.mark.req("FRG-IMP-010")
def test_slash_ranges_and_no_hardcoded_literals():
    r = parse("Detective Comics 112/113 (1946).cbz", reference_year=2026)
    assert r.issue is None
    assert r.issue_range is not None
    assert (r.issue_range.start, r.issue_range.end) == (112, 113)
    assert r.year == 1946
    # audit: no Mylar-style hardcoded per-title range literals anywhere
    for source in SRC.rglob("*.py"):
        text = source.read_text()
        for literal in ("112/113", "'9-5'", "'2 & 3'", "'4 & 5'", "380/381"):
            assert literal not in text, (source.name, literal)


@pytest.mark.req("FRG-IMP-010")
@pytest.mark.req("FRG-IMP-012")
def test_manga_chapter_ranges():
    r = parse("Berserk v01 c01-05.cbz", reference_year=2026)
    assert r.volume_ordinal == 1
    assert r.issue_range is not None
    assert (r.issue_range.start, r.issue_range.end) == (1, 5)
    assert r.issue_range.display == "c01-05"
    assert r.issue is None


@pytest.mark.req("FRG-IMP-010")
@pytest.mark.req("FRG-IMP-013")
def test_dates_are_not_ranges():
    r = parse("Amazing Spider-Man 798 2018-05-22.cbz", reference_year=2026)
    assert r.issue_range is None
    assert r.issue.value == 798
    assert r.year == 2018
    r = parse("Saga 55 2018-05.cbz", reference_year=2026)
    assert r.issue_range is None
    assert r.year == 2018
