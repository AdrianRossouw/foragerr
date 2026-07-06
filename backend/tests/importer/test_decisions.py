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
@pytest.mark.req("FRG-PP-014")
def test_equal_format_is_arbitrated_by_the_duplicate_constraint():
    """Deliberate FRG-PP-014 re-pin of the old equal-format-is-not-an-upgrade
    row: a same-rung tie is no longer the upgrade spec's rejection — the
    duplicate constraint owns it. With an unknown existing size the default
    larger-size constraint conservatively keeps the existing file, so the
    verdict is still a rejection, now with the constraint's visible reason."""
    decision = decide(
        _ev(existing_file_path="/lib/old.cbz", existing_format="cbz", new_format="cbz")
    )
    assert not decision.approved
    specs_hit = {r.spec for r in decision.rejections}
    assert "upgrade-allowed" not in specs_hit  # the tie is not the upgrade spec's
    rej = next(r for r in decision.rejections if r.spec == "duplicate-constraint")
    assert "larger-size" in rej.reason


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
        "duplicate-constraint",
    ]


# --- FRG-PP-014: same-rung duplicate constraint ------------------------------
#
# The upgrade spec and the duplicate spec partition on the profile-ladder rank:
# strict > (upgrade, accepted) and strict < (downgrade, rejected) stay the
# upgrade spec's byte-identical verdicts; ONLY the == tie reaches the duplicate
# constraint. Tie order: (fN) fixed-release markers first, then the configured
# constraint (larger-size default | preferred-format).


def _tie(**overrides) -> ImportEvaluation:
    """A same-rung (cbz vs cbz) collision with a known existing size."""
    base = dict(
        existing_file_path="/lib/old.cbz",
        existing_format="cbz",
        new_format="cbz",
        existing_size=4_000_000,
        size=5_000_000,
    )
    base.update(overrides)
    return _ev(**base)


@pytest.mark.req("FRG-PP-014")
def test_profile_order_still_decides_first_and_is_unchanged():
    """Scenario 1 pin: > imports as an upgrade exactly as before; < is rejected
    by the upgrade spec with the same reason as before; the duplicate spec never
    speaks for either."""
    up = decide(
        _ev(existing_file_path="/lib/old.cbr", existing_format="cbr", new_format="cbz")
    )
    assert up.approved  # genuine upgrade — byte-identical accept
    down = decide(
        _ev(existing_file_path="/lib/old.cbz", existing_format="cbz", new_format="cbr")
    )
    assert not down.approved
    rej = next(r for r in down.rejections if r.spec == "upgrade-allowed")
    assert "not an upgrade" in rej.reason  # byte-identical downgrade reason
    assert not any(r.spec == "duplicate-constraint" for r in down.rejections)


@pytest.mark.req("FRG-PP-014")
def test_larger_size_tie_lets_a_strictly_larger_file_win():
    assert decide(_tie(size=5_000_000, existing_size=4_000_000)).approved


@pytest.mark.req("FRG-PP-014")
def test_larger_size_tie_rejects_a_not_larger_file_with_a_visible_reason():
    for size in (4_000_000, 3_000_000):  # equal and smaller both lose
        decision = decide(_tie(size=size, existing_size=4_000_000))
        assert not decision.approved
        rej = next(r for r in decision.rejections if r.spec == "duplicate-constraint")
        assert "larger-size" in rej.reason
        assert "not larger" in rej.reason


@pytest.mark.req("FRG-PP-014")
def test_preferred_format_tie_keeps_the_existing_file():
    """A same-rung tie means the format preference is already satisfied, so the
    preferred-format constraint keeps the existing file even against a larger
    incoming one."""
    decision = decide(
        _tie(duplicate_constraint="preferred-format", size=9_000_000)
    )
    assert not decision.approved
    rej = next(r for r in decision.rejections if r.spec == "duplicate-constraint")
    assert "preferred-format" in rej.reason


@pytest.mark.req("FRG-PP-014")
def test_fix_marker_beats_the_size_constraint():
    """Scenario 3: a newer fixed release wins even when strictly smaller."""
    decision = decide(
        _tie(new_fix_revision=1, size=1_000_000, existing_size=4_000_000)
    )
    assert decision.approved


@pytest.mark.req("FRG-PP-014")
def test_fix_marker_beats_the_preferred_format_constraint():
    decision = decide(
        _tie(duplicate_constraint="preferred-format", new_fix_revision=1)
    )
    assert decision.approved


@pytest.mark.req("FRG-PP-014")
def test_an_unfixed_file_never_beats_a_fixed_one():
    """Even a much larger unfixed file loses to a fixed existing release."""
    decision = decide(
        _tie(existing_fix_revision=1, size=9_000_000, existing_size=1_000_000)
    )
    assert not decision.approved
    rej = next(r for r in decision.rejections if r.spec == "duplicate-constraint")
    assert "f1" in rej.reason and "fixed" in rej.reason


@pytest.mark.req("FRG-PP-014")
def test_a_higher_fix_revision_beats_a_lower_one():
    assert decide(_tie(new_fix_revision=2, existing_fix_revision=1)).approved
    lower = decide(_tie(new_fix_revision=1, existing_fix_revision=2))
    assert not lower.approved
    assert any(r.spec == "duplicate-constraint" for r in lower.rejections)


@pytest.mark.req("FRG-PP-014")
def test_equal_fix_markers_fall_back_to_the_configured_constraint():
    """Scenario 3 tail: equal markers → the constraint decides."""
    # larger-size: the bigger equal-marker file wins, the smaller one loses.
    assert decide(
        _tie(new_fix_revision=1, existing_fix_revision=1, size=5_000_000)
    ).approved
    equal = decide(
        _tie(new_fix_revision=1, existing_fix_revision=1, size=4_000_000)
    )
    assert not equal.approved
    # preferred-format: equal markers keep the existing file.
    pf = decide(
        _tie(
            new_fix_revision=1,
            existing_fix_revision=1,
            duplicate_constraint="preferred-format",
            size=9_000_000,
        )
    )
    assert not pf.approved


@pytest.mark.req("FRG-PP-014")
def test_duplicate_spec_is_silent_without_an_existing_file():
    decision = decide(_ev(existing_file_path=None))
    assert decision.approved
