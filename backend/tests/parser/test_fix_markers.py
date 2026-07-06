"""`(fN)` fixed-release marker annotation (FRG-PP-014 parser extension).

A re-released "fixed" scan carries a standalone trailing `(f1)`/`(f2)` group
near the extension (common scene naming). The parser captures it as
``ParseResult.fix_revision`` plus a ``fix-marker`` annotation, guarded for
title plausibility: only a group sitting after the issue (or trailing, when no
issue was selected) reads as a marker, so an `f1` inside a series title never
false-positives. Corpus rows 79-81 pin the same behavior under the corpus
policy; these tests carry the FRG-PP-014 traceability tag.
"""

from __future__ import annotations

import pytest

from foragerr.parser import AnnotationKind, parse

REF = 2026


@pytest.mark.req("FRG-PP-014")
def test_trailing_fix_marker_sets_the_revision():
    r = parse("Batman 404 (1987) (f1).cbz", reference_year=REF)
    assert r.series_name == "Batman"
    assert r.fix_revision == 1
    assert ("fix-marker", "f1") in {(a.kind.value, a.text) for a in r.annotations}


@pytest.mark.req("FRG-PP-014")
def test_higher_revisions_and_case_and_brackets_are_accepted():
    assert parse("Batman 404 (1987) (f2).cbz", reference_year=REF).fix_revision == 2
    assert parse("Batman 404 (1987) (F3).cbz", reference_year=REF).fix_revision == 3
    assert parse("Batman 404 (1987) [f2].cbz", reference_year=REF).fix_revision == 2


@pytest.mark.req("FRG-PP-014")
def test_unfixed_names_have_no_revision():
    assert parse("Batman 404 (1987).cbz", reference_year=REF).fix_revision is None


@pytest.mark.req("FRG-PP-014")
def test_title_plausibility_guard_a_marker_shape_inside_the_title_is_not_a_marker():
    """An `(f1)` group BEFORE the issue is title context, never a fix marker."""
    r = parse("Batman (f1) 404 (1987).cbz", reference_year=REF)
    assert r.fix_revision is None
    kinds = {a.text: a.kind for a in r.annotations}
    assert kinds.get("f1") is AnnotationKind.GENERIC


@pytest.mark.req("FRG-PP-014")
def test_marker_lookalikes_are_not_markers():
    # A bare trailing word (no group) and non-fN group content never match.
    assert parse("Batman 404 (1987) f2.cbz", reference_year=REF).fix_revision is None
    assert parse("Batman 404 (1987) (fix).cbz", reference_year=REF).fix_revision is None
    assert parse("Batman 404 (1987) (f2b).cbz", reference_year=REF).fix_revision is None


@pytest.mark.req("FRG-PP-014")
def test_marker_is_never_mistaken_for_the_scan_group():
    """Pre-change, a trailing `(f2)` was the last generic group and won the
    scan-group selection; the re-kinded marker must not."""
    r = parse("Batman 404 (1987) (f2).cbz", reference_year=REF)
    assert r.scan_group is None
    r = parse(
        "Saga 055 (2019) (Digital) (f1) (Son of Ultron-Empire).cbz",
        reference_year=REF,
    )
    assert r.fix_revision == 1
    assert r.scan_group == "Son of Ultron-Empire"
