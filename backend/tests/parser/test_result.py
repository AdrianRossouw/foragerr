"""FRG-IMP-003 — structured result, confidence, no sentinels, no crashes."""

import dataclasses
import re

import pytest
from corpus import CORPUS

from foragerr.parser import (
    DEFAULT_OPTIONS,
    FailureReason,
    ParseResult,
    parse,
)

SENTINELS = ("XCV", "c11", "f11", "g11", "h11", "999999999999999")


@pytest.mark.req("FRG-IMP-003")
def test_absent_fields_are_none_never_sentinels():
    r = parse("Batman 404.cbz", reference_year=2026)
    assert r.failure_reason is None
    assert r.series_name == "Batman"
    assert r.issue.value == 404
    assert r.year is None
    assert r.volume_ordinal is None
    assert r.volume_year is None
    assert r.scan_group is None
    assert r.issue_id is None
    # schema validation: no sentinel placeholder anywhere in the result
    serialized = r.to_json()
    for sentinel in SENTINELS:
        assert sentinel not in serialized


@pytest.mark.req("FRG-IMP-003")
def test_titles_containing_sentinel_substrings_round_trip():
    r = parse("Project XCV 003 (2020).cbz", reference_year=2026)
    assert r.series_name == "Project XCV"
    r = parse("Apache c11 Squadron 01 (2019).cbz", reference_year=2026)
    assert r.series_name == "Apache c11 Squadron"
    assert r.issue.value == 1


@pytest.mark.req("FRG-IMP-003")
def test_unparseable_input_returns_structured_failure():
    for name in ("()()( ).cbz", "", "   ", ".cbz"):
        r = parse(name, reference_year=2026)
        assert isinstance(r, ParseResult)
        assert r.failure_reason in (
            FailureReason.NO_SERIES_TITLE,
            FailureReason.EMPTY_INPUT,
        )
        assert isinstance(r.confidence, float)
        assert not r.success
    # salvageable partial fields survive on the same result type
    r = parse("()()( ).cbz", reference_year=2026)
    assert r.type == "cbz"
    assert r.failure_reason is FailureReason.NO_SERIES_TITLE


@pytest.mark.req("FRG-IMP-003")
def test_single_status_vocabulary():
    ok = parse("Batman 404 (1987).cbz", reference_year=2026)
    bad = parse("()()( ).cbz", reference_year=2026)
    assert type(ok) is type(bad) is ParseResult
    assert ok.success and not bad.success
    # exactly one status channel: the failure_reason field
    fields = {f.name for f in dataclasses.fields(ParseResult)}
    assert "failure_reason" in fields
    assert not any(re.match(r".*(parse|process)_status", f) for f in fields)


@pytest.mark.req("FRG-IMP-003")
def test_confidence_discriminates_anchored_from_ambiguous():
    anchored = parse("Batman #404 (1987).cbr", reference_year=2026)
    ambiguous = parse("Preacher 01-66 Complete.cbz", reference_year=2026)
    assert isinstance(anchored.confidence, float)
    assert isinstance(ambiguous.confidence, float)
    assert anchored.confidence > ambiguous.confidence


@pytest.mark.req("FRG-IMP-003")
def test_token_trace_covers_every_token():
    opts = dataclasses.replace(DEFAULT_OPTIONS, include_trace=True)
    r = parse("Batman #404 (1987).cbr", reference_year=2026, options=opts)
    assert r.token_trace is not None
    assert [e.text for e in r.token_trace] == ["Batman", "#404", "(1987)"]
    assert all(e.role for e in r.token_trace)
    # trace is off by default (opt-in diagnostics)
    assert parse("Batman #404 (1987).cbr", reference_year=2026).token_trace is None


@pytest.mark.req("FRG-IMP-003")
def test_no_corpus_row_emits_sentinels():
    for row in CORPUS:
        serialized = parse(row.filename, reference_year=2026).to_json()
        for sentinel in SENTINELS:
            assert sentinel not in serialized, (row.n, sentinel)
