"""Import decision specification matrix (FRG-PP-005, FRG-PP-006, FRG-PP-008)."""

from __future__ import annotations

import pytest

from foragerr.importer.decisions import (
    ImportEvaluation,
    RejectionKind,
    decide,
    default_specs,
)
from foragerr.importer.evidence import Evidence
from foragerr.security.archives import ArchiveReport

_GOOD_ARCHIVE = ArchiveReport(ok=True, kind="zip", member_count=10, image_count=10)


def _ev(**overrides) -> ImportEvaluation:
    """A fully-passing evaluation, overridden per-scenario."""
    base = dict(
        evidence=Evidence(),
        size=5_000_000,
        series_id=1,
        issue_id=1,
        archive=_GOOD_ARCHIVE,
        existing_file_path=None,
        existing_format=None,
        new_format="cbz",
        format_ladder=("pdf", "cbr", "cbz"),
        free_bytes=10_000_000_000,
        needed_bytes=5_000_000,
        margin_bytes=100_000_000,
        already_imported=False,
        junk_size_floor=100_000,
    )
    base.update(overrides)
    return ImportEvaluation(**base)


@pytest.mark.req("FRG-PP-005")
def test_all_pass_imports():
    decision = decide(_ev())
    assert decision.approved
    assert decision.reasons == ()


@pytest.mark.req("FRG-PP-005")
def test_all_specs_run_and_each_yields_a_reason():
    # Break several specs at once; every one must contribute a visible reason
    # (all-run, not short-circuited).
    decision = decide(
        _ev(
            series_id=None,
            issue_id=None,
            size=10,  # junk
            free_bytes=0,  # no space
        )
    )
    specs_hit = {r.spec for r in decision.rejections}
    assert "mapped-to-issue" in specs_hit
    assert "not-a-sample" in specs_hit
    assert "free-space" in specs_hit
    assert all(r.reason for r in decision.rejections)  # each reason user-visible


@pytest.mark.req("FRG-PP-005")
def test_unmatched_blocks_not_lost():
    decision = decide(_ev(series_id=None, issue_id=None))
    assert not decision.approved
    assert not decision.failed  # blocked (needs action), not a failed archive
    assert any("known series and issue" in r for r in decision.reasons)


@pytest.mark.req("FRG-PP-006")
def test_corrupt_archive_routes_to_failed():
    bad = ArchiveReport(
        ok=False, kind="zip", reason_code="corrupt_zip", reason="not a valid zip archive"
    )
    decision = decide(_ev(archive=bad))
    assert not decision.approved
    assert decision.failed  # FRG-PP-006: corrupt → failed-download handling
    rej = next(r for r in decision.rejections if r.spec == "archive-valid")
    assert rej.kind is RejectionKind.FAILED
    assert "not a valid zip" in rej.reason


@pytest.mark.req("FRG-PP-005")
def test_equal_format_is_not_an_upgrade():
    decision = decide(
        _ev(existing_file_path="/lib/old.cbz", existing_format="cbz", new_format="cbz")
    )
    assert not decision.approved
    rej = next(r for r in decision.rejections if r.spec == "upgrade-allowed")
    assert "not an upgrade" in rej.reason


@pytest.mark.req("FRG-PP-005")
def test_better_format_is_an_upgrade():
    decision = decide(
        _ev(existing_file_path="/lib/old.cbr", existing_format="cbr", new_format="cbz")
    )
    assert decision.approved  # cbz outranks cbr in the ladder


@pytest.mark.req("FRG-PP-005")
def test_already_imported_for_this_download_blocks():
    decision = decide(_ev(already_imported=True))
    assert not decision.approved
    assert any(r.spec == "not-already-imported" for r in decision.rejections)


@pytest.mark.req("FRG-PP-008")
def test_unmapped_remote_path_blocks_naming_the_fix():
    decision = decide(
        _ev(mapping_warning="check remote path mapping", series_id=None, issue_id=None)
    )
    assert not decision.approved
    reasons = " ".join(decision.reasons)
    assert "remote-path mapping" in reasons
    # The mapping failure owns the block; downstream specs stay quiet (guarded).
    specs_hit = {r.spec for r in decision.rejections}
    assert specs_hit == {"remote-path-mapped"}


@pytest.mark.req("FRG-PP-005")
def test_spec_order_is_stable():
    names = [s.name for s in default_specs()]
    assert names == [
        "remote-path-mapped",
        "mapped-to-issue",
        "embedded-id-conflict",
        "archive-valid",
        "not-a-sample",
        "free-space",
        "not-already-imported",
        "upgrade-allowed",
    ]
