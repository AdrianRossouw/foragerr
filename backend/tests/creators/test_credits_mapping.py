"""Credit ingest mapping totality + sanitization (FRG-CRTR-001, FRG-META-006).

Pure mapper tests: ``map_issue`` / ``map_person_credits`` turn an untrusted CV
``person_credits`` value into typed, sanitized credit records, and are total —
present -> typed entries, anything else -> an empty list, never an error.
"""

from __future__ import annotations

import pytest

import logging

from foragerr.metadata.credits import MAX_CREDITS_PER_ISSUE, map_person_credits
from foragerr.metadata.mapping import map_issue
from foragerr.metadata.models import CreditRecord


def issue_payload(**overrides) -> dict:
    """A minimal well-formed CV issue ``results`` object for mapper tests."""
    base = {"id": 348871, "name": "Chapter One", "issue_number": "1"}
    base.update(overrides)
    return base


def _credit(cv_person_id: int, name: str, role: str) -> dict:
    return {"id": cv_person_id, "name": name, "role": role}


@pytest.mark.req("FRG-CRTR-001")
def test_wellformed_credits_map_to_typed_records():
    rec = map_issue(
        issue_payload(
            person_credits=[
                _credit(10, "Alice Writer", "writer"),
                _credit(11, "Bob Artist", "artist"),
            ]
        )
    )
    assert all(isinstance(c, CreditRecord) for c in rec.credits)
    by_person = {c.cv_person_id: c for c in rec.credits}
    assert by_person[10].name == "Alice Writer"
    assert by_person[10].role_normalized == "writer"
    assert by_person[10].role_verbatim == "writer"
    assert by_person[11].role_normalized == "artist"


@pytest.mark.req("FRG-META-006")
@pytest.mark.req("FRG-CRTR-001")
def test_absent_credits_map_to_empty_list():
    # issue_payload has no person_credits at all
    assert map_issue(issue_payload()).credits == ()


@pytest.mark.req("FRG-META-006")
@pytest.mark.req("FRG-CRTR-001")
def test_empty_credits_list_maps_to_empty():
    assert map_issue(issue_payload(person_credits=[])).credits == ()


@pytest.mark.req("FRG-META-006")
@pytest.mark.req("FRG-CRTR-001")
@pytest.mark.parametrize(
    "malformed",
    ["garbage", 42, {"id": 1}, [1, 2, 3], [None, "x"]],
)
def test_malformed_credits_value_maps_to_empty_without_error(malformed):
    rec = map_issue(issue_payload(person_credits=malformed))
    assert isinstance(rec.credits, tuple)
    # the rest of the issue still maps normally
    assert rec.issue_number == "1"


@pytest.mark.req("FRG-CRTR-001")
def test_entries_missing_or_invalid_id_are_dropped():
    credits = map_person_credits(
        [
            _credit(0, "Zero Id", "writer"),  # non-positive id -> dropped
            {"name": "No Id", "role": "writer"},  # missing id -> dropped
            {"id": "not-a-number", "name": "X", "role": "writer"},  # invalid
            _credit(10, "Kept", "writer"),
        ]
    )
    assert [c.cv_person_id for c in credits] == [10]


@pytest.mark.req("FRG-CRTR-001")
def test_entries_with_empty_name_are_dropped():
    credits = map_person_credits(
        [
            _credit(10, "   ", "writer"),  # whitespace-only -> sanitizes to nothing
            _credit(11, "<script>x</script>", "writer"),  # all-markup -> nothing
            _credit(12, "Real Name", "writer"),
        ]
    )
    assert [c.cv_person_id for c in credits] == [12]


@pytest.mark.req("FRG-CRTR-001")
def test_hostile_unicode_name_is_sanitized_at_ingest():
    # RLO override + zero-width space + HTML + control char in the name
    hostile = "‮Evil​ <b>Name</b>\x07"
    credits = map_person_credits([_credit(10, hostile, "writer")])
    assert len(credits) == 1
    name = credits[0].name
    assert "‮" not in name and "​" not in name
    assert "\x07" not in name and "<b>" not in name
    assert "Name" in name


@pytest.mark.req("FRG-CRTR-001")
def test_hostile_role_string_is_sanitized_at_ingest():
    credits = map_person_credits([_credit(10, "Alice", "<b>writer</b>")])
    assert len(credits) == 1
    assert credits[0].role_normalized == "writer"
    assert "<b>" not in credits[0].role_verbatim


@pytest.mark.req("FRG-CRTR-001")
def test_compound_role_splits_into_one_record_per_normalized_role():
    credits = map_person_credits([_credit(10, "Alice", "penciler, inker, colorist")])
    roles = {c.role_normalized for c in credits}
    assert roles == {"penciler", "inker", "colorist"}
    assert all(c.cv_person_id == 10 for c in credits)


@pytest.mark.req("FRG-CRTR-001")
def test_duplicate_person_and_role_collapse():
    credits = map_person_credits(
        [
            _credit(10, "Alice", "writer, writer"),  # same normalized twice
            _credit(10, "Alice", "writer"),  # repeated across entries
        ]
    )
    assert len(credits) == 1
    assert credits[0].role_normalized == "writer"


@pytest.mark.req("FRG-CRTR-001")
def test_credited_person_without_a_role_is_kept_as_other():
    credits = map_person_credits([{"id": 10, "name": "Alice"}])
    assert len(credits) == 1
    assert credits[0].role_normalized == "other"


@pytest.mark.req("FRG-CRTR-001")
def test_oversized_payload_is_capped_per_issue(caplog):
    """A hostile/oversized CV payload is bounded to MAX_CREDITS_PER_ISSUE after
    dedup, so one issue can never explode into an unbounded credit insert
    (RISK-011). Excess entries are dropped with a single debug log, no error."""
    entries = [_credit(i, f"Person {i}", "writer") for i in range(1, 151)]
    with caplog.at_level(logging.DEBUG, logger="foragerr.metadata.credits"):
        credits = map_person_credits(entries)

    assert len(credits) == MAX_CREDITS_PER_ISSUE  # 150 well-formed -> capped 100
    cap_logs = [r for r in caplog.records if "capping" in r.getMessage()]
    assert len(cap_logs) == 1  # exactly one truncation log emitted
