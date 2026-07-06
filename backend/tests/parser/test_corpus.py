"""Parametrized executor for the regression corpus (FRG-IMP-021).

Each row runs as its own test case carrying the row's requirement-ID marks,
so the traceability matrix regenerates from this file plus ``corpus.py``.
"""

from fractions import Fraction

import pytest
from corpus import CORPUS, Row

from foragerr.parser import parse

REFERENCE_YEAR = 2026  # pinned so 2099-style rows never rot (FRG-IMP-002)


def _params():
    return [
        pytest.param(row, id=f"row{row.n:02d}", marks=[pytest.mark.req(r) for r in row.reqs])
        for row in CORPUS
    ]


@pytest.mark.req("FRG-IMP-021")
@pytest.mark.parametrize("row", _params())
def test_corpus_row(row: Row):
    r = parse(row.filename, reference_year=REFERENCE_YEAR)

    assert r.failure_reason is None, f"row {row.n} failed: {r.failure_reason}"
    assert r.series_name == row.series
    assert r.matching_key is not None

    if row.issue is not None or row.issue_name is not None:
        assert r.issue is not None, f"row {row.n}: expected an issue record"
        if row.issue is not None:
            assert r.issue.value == Fraction(row.issue)
        else:
            assert r.issue.value is None
        assert r.issue.display == row.display
        assert r.issue.suffix == row.suffix
        assert r.issue.name == row.issue_name
        assert r.issue.classification.value == row.classification
    else:
        assert r.issue is None, f"row {row.n}: unexpected issue {r.issue}"

    if row.range_start is not None:
        assert r.issue_range is not None
        assert r.issue_range.start == Fraction(row.range_start)
        assert r.issue_range.end == Fraction(row.range_end)
        assert r.issue_range.display == row.range_display
    else:
        assert r.issue_range is None

    if row.total is not None:
        assert r.miniseries_total == Fraction(row.total)
    else:
        assert r.miniseries_total is None

    assert r.volume_ordinal == row.vol
    assert r.volume_year == row.vol_year
    assert r.year == row.year
    assert r.booktype.value == row.booktype
    assert r.scan_group == row.scan_group
    assert r.fix_revision == row.fix_revision
    assert r.issue_id == row.issue_id
    assert r.type == row.ext
    assert r.alt_series == row.alt_series
    assert r.alt_issue_title == row.alt_issue_title

    have = {(a.kind.value, a.text) for a in r.annotations}
    for expected in row.annotations_contain:
        assert expected in have, f"row {row.n}: missing annotation {expected}"


@pytest.mark.req("FRG-IMP-021")
def test_corpus_is_complete_and_traceable():
    """All 75 seed rows present (additive growth beyond them is allowed);
    every row carries at least one requirement tag."""
    assert len(CORPUS) >= 75
    for row in CORPUS:
        assert row.reqs, f"row {row.n} has no requirement tags"
        for rid in row.reqs:
            assert rid.startswith("FRG-IMP-")
