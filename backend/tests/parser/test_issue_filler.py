"""FRG-IMP-026 — bare `Issue`/`Issues` filler stripping.

Store-source filenames introduce the number with a bare filler word
(`CINDER Issue # 279`, `Duskmarch Issues #8`), which otherwise leaks into
the series title and defeats matching. The rule is anchored and narrow: the
word is consumed only when it sits directly on the issue evidence — the
issue-anchor `#` or the token selected as the issue number. Corpus rows 82-87
pin the same shapes under the corpus policy (FRG-IMP-021).
"""

from __future__ import annotations

import pytest

from foragerr.parser import parse

REF = 2026


@pytest.mark.req("FRG-IMP-026")
def test_filler_before_a_spaced_anchor_is_stripped():
    r = parse("CINDER Issue # 279.cbz", reference_year=REF)
    assert r.series_name == "CINDER"
    assert r.issue.value == 279


@pytest.mark.req("FRG-IMP-026")
def test_filler_before_a_glued_anchor_is_stripped():
    r = parse("Duskmarch Issues #8.cbz", reference_year=REF)
    assert r.series_name == "Duskmarch"
    assert r.issue.value == 8


@pytest.mark.req("FRG-IMP-026")
def test_filler_before_an_unanchored_issue_number_is_stripped():
    r = parse("Cinder Issue 211.cbz", reference_year=REF)
    assert r.series_name == "Cinder"
    assert r.issue.value == 211


@pytest.mark.req("FRG-IMP-026")
def test_mid_title_issue_word_is_preserved():
    # `Issue` is followed by title words, not the issue evidence.
    r = parse("The Death Issue Files 004 (2019).cbz", reference_year=REF)
    assert r.series_name == "The Death Issue Files"
    assert r.issue.value == 4
    # ... and with no issue evidence at all it is plain title content.
    r = parse("The Death Issue (2019).cbz", reference_year=REF)
    assert r.series_name == "The Death Issue"
    assert r.issue is None


@pytest.mark.req("FRG-IMP-026")
def test_filler_is_never_stripped_from_the_head_of_the_name():
    # Consuming index 0 would leave no series title at all; the leading token
    # stays, exactly as the `Part N` cue rule does.
    r = parse("Issue #5.cbz", reference_year=REF)
    assert r.series_name == "Issue"
    assert r.issue.value == 5


@pytest.mark.req("FRG-IMP-026")
def test_stripping_leaves_the_rest_of_the_parse_intact():
    r = parse("Hellboy Issue #2 - The Wolves (2000).cbz", reference_year=REF)
    assert r.series_name == "Hellboy"
    assert r.issue.value == 2
    assert r.alt_issue_title == "The Wolves"
    assert r.year == 2000
