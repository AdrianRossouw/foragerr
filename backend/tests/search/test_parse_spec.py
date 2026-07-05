"""FRG-SRCH-002 — parser calling contract: failure is a rejection, never a raise."""

from __future__ import annotations

from fractions import Fraction

import pytest

from foragerr.search import DecisionEngine, RejectionType, SearchTarget
from foragerr.search.specs import ParseSpec
from foragerr.search.specs.base import Evaluation
from foragerr.search.mapping import NO_MAPPING
from foragerr.parser import parse

from .builders import candidate, context, issue, series

ENGINE = DecisionEngine()


def _ev(title: str) -> Evaluation:
    parsed = parse(title, reference_year=2026)
    return Evaluation(candidate=candidate(title), parsed=parsed, mapping=NO_MAPPING, fmt=None)


@pytest.mark.req("FRG-SRCH-002")
def test_empty_title_is_permanent_parse_rejection_not_exception():
    d = ENGINE.evaluate(candidate(""), context())
    parse_rej = [r for r in d.rejections if r.spec == "parse"]
    assert len(parse_rej) == 1
    assert parse_rej[0].type is RejectionType.PERMANENT
    assert "empty-input" in parse_rej[0].reason


@pytest.mark.req("FRG-SRCH-002")
def test_parse_spec_carries_parser_machine_reason():
    rej = ParseSpec().evaluate(_ev(""), context())
    assert rej is not None
    # the parser's FailureReason value must be embedded verbatim
    assert "empty-input" in rej.reason


@pytest.mark.req("FRG-SRCH-002")
def test_parse_spec_accepts_a_parseable_title():
    assert ParseSpec().evaluate(_ev("Batman 005 (2016)"), context()) is None


@pytest.mark.req("FRG-SRCH-002")
def test_engine_uses_the_one_shared_parser_identically():
    # The parsed structure on the decision is exactly what the shared parser
    # yields for the same title + reference year (no engine-local parsing).
    title = "Saga 012 (2018)"
    d = ENGINE.evaluate(candidate(title), context(now=__import__("datetime").datetime(2026, 1, 1)))
    assert d.parsed.to_json() == parse(title, reference_year=2026).to_json()


@pytest.mark.req("FRG-SRCH-002")
def test_comic_grade_issue_number_preserved_for_mapping():
    # A suffixed issue like 1.MU must map to a like-suffixed library issue.
    s = series(1, "batman", issues=(issue(10, 1, suffix="MU"),))
    ctx = context(s, target=SearchTarget(series_id=1, issue_id=10))
    d = ENGINE.evaluate(candidate("Batman 1.MU (2016)"), ctx)
    assert d.mapped_issue_id == 10
    assert d.parsed.issue is not None
    assert d.parsed.issue.value == Fraction(1)


@pytest.mark.req("FRG-SRCH-002")
def test_decimal_issue_number_preserved():
    s = series(1, "batman", issues=(issue(10, Fraction(3, 2)),))  # 1.5
    ctx = context(s, target=SearchTarget(series_id=1, issue_id=10))
    d = ENGINE.evaluate(candidate("Batman 1.5 (2016)"), ctx)
    assert d.mapped_issue_id == 10
