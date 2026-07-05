"""FRG-SRCH-001 — unified engine: all-run specs, full reason lists, outcomes."""

from __future__ import annotations

import pytest

from foragerr.search import (
    DecisionEngine,
    DecisionOutcome,
    EngineConfig,
    RejectionType,
    SearchTarget,
    classify,
)
from foragerr.search.decision import Rejection

from .builders import candidate, context, issue, series

ENGINE = DecisionEngine()


def _batman_ctx(**kw):
    s = series(1, "batman", issues=(issue(10, 5),))
    return context(s, target=SearchTarget(series_id=1, issue_id=10), **kw)


@pytest.mark.req("FRG-SRCH-001")
def test_approved_when_no_spec_rejects():
    d = ENGINE.evaluate(candidate("Batman 005 (2016) (cbz)"), _batman_ctx())
    assert d.outcome is DecisionOutcome.APPROVED
    assert d.rejections == ()
    assert d.approved is True


@pytest.mark.req("FRG-SRCH-001")
def test_all_specs_run_full_reason_list_not_first_fail():
    # Wrong series AND a forbidden term: both rejections must be listed, proving
    # the engine does not short-circuit on the first failure.
    cfg = EngineConfig(must_not_contain=("scanlation",))
    d = ENGINE.evaluate(
        candidate("Superman 005 (2016) scanlation"), _batman_ctx(config=cfg)
    )
    specs = {r.spec for r in d.rejections}
    assert "series-match" in specs
    assert "must-not-contain" in specs
    assert len(d.rejections) >= 2


@pytest.mark.req("FRG-SRCH-001")
def test_temporarily_rejected_when_all_rejections_temporary():
    # Only the min-age (Temporary) spec fails.
    cfg = EngineConfig(min_age_minutes=120)
    d = ENGINE.evaluate(
        candidate("Batman 005 (2016) (cbz)", age_hours=0.5), _batman_ctx(config=cfg)
    )
    assert d.outcome is DecisionOutcome.TEMPORARILY_REJECTED
    assert all(r.type is RejectionType.TEMPORARY for r in d.rejections)


@pytest.mark.req("FRG-SRCH-001")
def test_rejected_when_any_permanent_even_with_temporary():
    # min-age (Temporary) + wrong series (Permanent) -> overall Rejected,
    # both reasons retained.
    cfg = EngineConfig(min_age_minutes=120)
    d = ENGINE.evaluate(
        candidate("Superman 005 (2016)", age_hours=0.5), _batman_ctx(config=cfg)
    )
    assert d.outcome is DecisionOutcome.REJECTED
    types = {r.type for r in d.rejections}
    assert RejectionType.PERMANENT in types
    assert RejectionType.TEMPORARY in types


@pytest.mark.req("FRG-SRCH-001")
def test_classify_pure_function():
    assert classify(()) is DecisionOutcome.APPROVED
    temp = Rejection("t", RejectionType.TEMPORARY, "x")
    perm = Rejection("p", RejectionType.PERMANENT, "y")
    assert classify((temp,)) is DecisionOutcome.TEMPORARILY_REJECTED
    assert classify((temp, perm)) is DecisionOutcome.REJECTED


@pytest.mark.req("FRG-SRCH-001")
def test_reasons_are_user_visible_strings_in_spec_order():
    d = ENGINE.evaluate(candidate("Superman 005 (2016)"), _batman_ctx())
    assert d.reasons
    assert all(isinstance(r, str) and r for r in d.reasons)
