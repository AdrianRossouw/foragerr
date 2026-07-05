"""FRG-SRCH-003 — release-to-library mapping: aliases, disambiguation, distinct
unknown-series / unknown-issue rejections."""

from __future__ import annotations

import pytest

from foragerr.parser import parse
from foragerr.parser.normalize import matching_key
from foragerr.search import DecisionEngine, RejectionType
from foragerr.search.mapping import map_release

from .builders import candidate, context, issue, series

ENGINE = DecisionEngine()


def _reasons_by_spec(decision):
    return {r.spec: r for r in decision.rejections}


@pytest.mark.req("FRG-SRCH-003")
def test_alias_maps_release_to_the_right_series():
    # Series primary key "the amazing spider man"; the release uses a short
    # alias "spidey" that the user added.
    s = series(
        7,
        matching_key("The Amazing Spider-Man"),
        issues=(issue(70, 5),),
        aliases=(matching_key("Spidey"),),
    )
    ctx = context(s)  # no target: pure mapping path
    d = ENGINE.evaluate(candidate("Spidey 005 (2016)"), ctx)
    assert d.mapped_series_id == 7
    assert d.mapped_issue_id == 70


@pytest.mark.req("FRG-SRCH-003")
def test_year_volume_disambiguation_between_same_named_series():
    v2011 = series(1, "batman", issues=(issue(11, 5),), start_year=2011)
    v2016 = series(2, "batman", issues=(issue(21, 5),), start_year=2016)
    ctx = context(v2011, v2016)
    # The release carries (2016) -> must resolve to the 2016 volume.
    d = ENGINE.evaluate(candidate("Batman 005 (2016)"), ctx)
    assert d.mapped_series_id == 2
    assert d.mapped_issue_id == 21


@pytest.mark.req("FRG-SRCH-003")
def test_ambiguous_same_key_without_year_is_unknown_series():
    v1 = series(1, "batman", issues=(issue(11, 5),), start_year=2011)
    v2 = series(2, "batman", issues=(issue(21, 5),), start_year=2016)
    ctx = context(v1, v2)
    # No year on the release and two same-key volumes -> cannot disambiguate.
    d = ENGINE.evaluate(candidate("Batman 005"), ctx)
    assert d.mapped_series_id is None
    assert "series-match" in _reasons_by_spec(d)


@pytest.mark.req("FRG-SRCH-003")
def test_unknown_series_is_a_distinct_permanent_rejection():
    s = series(1, "batman", issues=(issue(10, 5),))
    d = ENGINE.evaluate(candidate("Daredevil 005 (2016)"), context(s))
    rej = _reasons_by_spec(d)
    assert "series-match" in rej
    assert rej["series-match"].type is RejectionType.PERMANENT
    assert "Unknown series" in rej["series-match"].reason
    assert "issue-match" not in rej  # not a cascade


@pytest.mark.req("FRG-SRCH-003")
def test_unknown_issue_is_a_distinct_permanent_rejection():
    s = series(1, "batman", issues=(issue(10, 5),))
    d = ENGINE.evaluate(candidate("Batman 099 (2016)"), context(s))
    rej = _reasons_by_spec(d)
    assert d.mapped_series_id == 1
    assert "issue-match" in rej
    assert rej["issue-match"].type is RejectionType.PERMANENT
    assert "Unknown issue" in rej["issue-match"].reason
    assert "series-match" not in rej


@pytest.mark.req("FRG-SRCH-003")
def test_substring_series_names_do_not_false_match():
    # Exact normalized-key matching: "Spawn" must not swallow "Curse of Spawn".
    spawn = series(1, matching_key("Spawn"), issues=(issue(10, 5),))
    ctx = context(spawn)
    d = map_release(parse("Curse of Spawn 005 (2016)", reference_year=2026), ctx)
    assert d.series is None


@pytest.mark.req("FRG-SRCH-003")
def test_map_release_is_pure_no_side_effects():
    s = series(1, "batman", issues=(issue(10, 5),))
    ctx = context(s)
    parsed = parse("Batman 005 (2016)", reference_year=2026)
    a = map_release(parsed, ctx)
    b = map_release(parsed, ctx)
    assert a.series is b.series and a.issue is b.issue
