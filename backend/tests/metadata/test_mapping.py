"""Volume/issue mapping to typed, sentinel-free records (FRG-META-005/006)."""

from __future__ import annotations

import logging

import pytest

from foragerr.metadata.mapping import map_issue, map_volume
from foragerr.metadata.models import IssueRecord, SeriesRecord
from fixtures import HOSTILE_DESCRIPTION, issue_payload, volume_payload

_SENTINELS = ("None", "Unknown", "0000", "0000-00-00", "N/A")


@pytest.mark.req("FRG-META-005")
def test_wellformed_volume_maps_to_typed_record():
    rec = map_volume(volume_payload())
    assert isinstance(rec, SeriesRecord)
    assert rec.cv_volume_id == 18166
    assert rec.name == "Saga"
    assert rec.publisher == "Image Comics"
    assert rec.start_year == 2012
    assert rec.aliases == ("Saga Comic", "BKV Saga")
    assert rec.site_url == "https://comicvine.gamespot.com/saga/4050-18166/"
    assert rec.first_issue is not None and rec.first_issue.issue_number == "1"
    assert rec.image_url.endswith("/saga.jpg")


@pytest.mark.req("FRG-META-005")
def test_element_count_wins_over_count_of_issues():
    # fixture: 4 issue elements vs count_of_issues=3
    rec = map_volume(volume_payload())
    assert rec.count_of_issues == 4


@pytest.mark.req("FRG-META-005")
def test_absent_fields_map_to_none_never_sentinels():
    rec = map_volume(
        volume_payload(
            publisher=None,
            start_year=None,
            description=None,
            first_issue=None,
            image=None,
            aliases=None,
            site_detail_url=None,
        )
    )
    assert rec.publisher is None
    assert rec.start_year is None
    assert rec.description is None
    assert rec.first_issue is None
    assert rec.image_url is None
    assert rec.aliases == ()
    for value in vars_of(rec):
        assert value not in _SENTINELS


@pytest.mark.req("FRG-META-005")
def test_zero_start_year_is_not_a_real_year():
    assert map_volume(volume_payload(start_year="0000")).start_year is None
    assert map_volume(volume_payload(start_year="0")).start_year is None


@pytest.mark.req("FRG-META-014")
def test_hostile_html_description_sanitized_at_map_time():
    rec = map_volume(volume_payload(description=HOSTILE_DESCRIPTION))
    assert rec.description is not None
    assert "<script" not in rec.description.lower()
    assert "alert" not in rec.description
    assert "space" in rec.description  # visible text kept


@pytest.mark.req("FRG-META-006")
def test_non_integer_issue_numbers_preserved_verbatim():
    for raw in ("1", "1.5", "1.MU", "½", "0", "-1", "Alpha"):
        rec = map_issue(issue_payload(issue_number=raw))
        assert rec.issue_number == raw
        assert isinstance(rec.issue_number, str)


@pytest.mark.req("FRG-META-006")
def test_missing_dates_map_to_null_not_sentinel():
    rec = map_issue(issue_payload(cover_date=None, store_date="0000-00-00"))
    assert rec.cover_date is None
    assert rec.store_date is None


@pytest.mark.req("FRG-META-006")
def test_unnumbered_issue_surfaced_with_exactly_one_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="foragerr.metadata.mapping"):
        rec = map_issue(issue_payload(id=999, issue_number=None))
    assert isinstance(rec, IssueRecord)
    assert rec.issue_number is None and rec.is_unnumbered is True
    warnings = [r for r in caplog.records if "unnumbered" in r.getMessage() or "no issue number" in r.getMessage()]
    assert len(warnings) == 1


@pytest.mark.req("FRG-META-006")
def test_hostile_title_sanitized_but_number_untouched():
    rec = map_issue(
        issue_payload(name="<script>x</script>Chapter <b>One</b>", issue_number="1.MU")
    )
    assert rec.issue_number == "1.MU"
    assert rec.title is not None and "script" not in rec.title.lower()
    assert "Chapter" in rec.title and "One" in rec.title


@pytest.mark.req("FRG-META-005")
def test_malformed_numeric_string_maps_to_none_not_a_crash():
    """A multi-sign numeric-looking string ("--5") must not raise ValueError
    out of the client's typed-exceptions-only contract."""
    rec = map_volume(
        volume_payload(id="--5", count_of_issues="--5", start_year="--5", issues=None)
    )
    assert rec.cv_volume_id == 0  # `_int(...) or 0` fallback, never a crash
    assert rec.start_year is None
    assert rec.count_of_issues is None


def vars_of(record) -> list[object]:
    """All scalar field values of a slotted dataclass, flattening tuples."""
    out: list[object] = []
    for name in record.__slots__:
        value = getattr(record, name)
        if isinstance(value, tuple):
            out.extend(value)
        else:
            out.append(value)
    return out
