"""Evidence aggregation + per-field provenance (FRG-PP-004, FRG-PP-003)."""

from __future__ import annotations

import pytest

from foragerr.importer.evidence import (
    LAYER_FILENAME,
    LAYER_FOLDER,
    LAYER_GRAB,
    PROV_ISSUE_ID_TAG,
    aggregate,
)
from foragerr.parser.normalize import matching_key


@pytest.mark.req("FRG-PP-004")
def test_single_parser_and_defined_source_order():
    # File name is junk; the folder + grab record carry the truth.
    ev = aggregate(
        grab_title="Batman 404 (1987)",
        file_name="downloaded_file_x0192.cbz",
        folder_name="Batman (1987)",
        client_title="batman.404",
        reference_year=2026,
    )
    assert ev.matching_key == matching_key("Batman")
    assert ev.issue is not None and str(ev.issue.value) == "404"
    # The grab record is the highest-confidence layer for series + issue.
    assert ev.provenance["series"] == LAYER_GRAB
    assert ev.provenance["issue"] == LAYER_GRAB


@pytest.mark.req("FRG-PP-004")
def test_junk_filename_overridden_by_better_sources_with_recorded_provenance():
    # The file name carries only the anchored issue (no series title); the
    # folder name resolves the series + year — provenance records each source.
    ev = aggregate(
        file_name="#052.cbz",
        folder_name="100 Bullets (2003)",
        reference_year=2026,
    )
    assert ev.matching_key == matching_key("100 Bullets")
    assert ev.provenance["series"] == LAYER_FOLDER
    assert ev.issue is not None and str(ev.issue.value) == "52"
    assert ev.provenance["issue"] == LAYER_FILENAME
    assert ev.year == 2003
    assert ev.provenance["year"] == LAYER_FOLDER


@pytest.mark.req("FRG-PP-003")
def test_issue_id_tag_captured_with_distinct_provenance():
    ev = aggregate(
        file_name="Some Comic [__12345__].cbz",
        reference_year=2026,
    )
    assert ev.issue_id == "12345"
    assert ev.provenance["issue_id"] == PROV_ISSUE_ID_TAG


@pytest.mark.req("FRG-PP-004")
def test_empty_candidate_yields_empty_evidence_without_raising():
    ev = aggregate(reference_year=2026)
    assert ev.matching_key is None
    assert ev.issue is None
    assert ev.provenance == {}
