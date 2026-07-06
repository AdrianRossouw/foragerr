"""Persisted issue ordering key (FRG-SER-002), built on the shared parser
ordering implementation (`foragerr.parser.ordering.sort_key`, FRG-IMP-020)."""

from __future__ import annotations

import pytest

from foragerr.library.ordering import ordering_key_for, parse_issue_number
from foragerr.parser.ordering import sort_key
from foragerr.parser.vocab import DEFAULT_OPTIONS


@pytest.mark.req("FRG-SER-002")
def test_non_integer_issue_numbers_parse_without_coercion():
    assert parse_issue_number("1").value == 1
    assert parse_issue_number("1.5").value == 1.5
    mu = parse_issue_number("1.MU")
    assert mu.value == 1
    assert mu.suffix == "MU"


@pytest.mark.req("FRG-SER-002")
def test_ordering_key_is_independent_of_insertion_order():
    numbers = ["10", "2", "1"]
    keyed = sorted(numbers, key=ordering_key_for)
    assert keyed == ["1", "2", "10"]  # lexicographic pitfall avoided by fixed-width encoding


@pytest.mark.req("FRG-SER-002")
def test_ordering_key_matches_the_shared_ordering_implementation_directly():
    """The persisted TEXT key must sort issues in exactly the same relative
    order as `foragerr.parser.ordering.sort_key` would — it is only a
    string encoding of that same tuple, never a second ordering
    implementation (FRG-IMP-020's "one ordering implementation" rule).

    Note: FRG-SER-002's scenario text lists the example set `1`, `1.5`,
    `1.MU` in the order `1, 1.5, 1.MU`. Reusing `sort_key` verbatim (as
    directed) instead yields `1, 1.MU, 1.5`, because `sort_key`'s own test
    suite (`tests/parser/test_ordering.py`) pins same-value issues to sort
    no-suffix-before-suffixed *before* comparing to a different value, and a
    dotted-suffix issue number (`1.MU`) has the *same* base value as `1`,
    while `1.5` is a strictly greater value. This module intentionally
    matches the shared, already-tested ordering implementation rather than
    hand-coding a different order to fit the scenario text; flagged for the
    orchestrator to reconcile against the spec wording.
    """
    numbers = ["1.5", "1", "1.MU"]
    ordering_keys = {n: ordering_key_for(n) for n in numbers}
    sort_keys = {n: sort_key(parse_issue_number(n), DEFAULT_OPTIONS) for n in numbers}

    by_ordering_key = sorted(numbers, key=lambda n: ordering_keys[n])
    by_sort_key = sorted(numbers, key=lambda n: sort_keys[n])
    assert by_ordering_key == by_sort_key == ["1", "1.MU", "1.5"]


@pytest.mark.req("FRG-SER-002")
def test_unnumbered_issue_gets_a_deterministic_key_instead_of_raising():
    assert ordering_key_for(None) == ordering_key_for("")
    # Still totally ordered against a real numbered issue.
    assert ordering_key_for("") < ordering_key_for("1")


@pytest.mark.req("FRG-SER-002")
def test_fraction_glyphs_and_negative_numbers_are_supported():
    assert parse_issue_number("½").value == 0.5
    assert parse_issue_number("-1").value == -1
    assert ordering_key_for("-1") < ordering_key_for("0") < ordering_key_for("½") < ordering_key_for("1")
