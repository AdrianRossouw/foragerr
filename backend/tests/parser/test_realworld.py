"""FRG-IMP-021 — real-world-style sweeps at corpus scale.

Two layers:
* a committed fixture list of 500 representative names (synthesized from the
  corpus patterns — no real library content) that runs unconditionally in CI;
* an env-gated sweep over a mounted library's actual filenames (names only,
  read-only) via ``FORAGERR_CORPUS_DIR``, enforcing the FRG-IMP-003 crash bar
  at real-library scale (~4.6k files).
"""

import os
import pathlib

import pytest

from foragerr.parser import FailureReason, ParseResult, parse

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "realworld_names.txt"
REFERENCE_YEAR = 2026


@pytest.mark.req("FRG-IMP-021")
@pytest.mark.req("FRG-IMP-003")
def test_committed_fixture_list_zero_crashes():
    names = [n for n in FIXTURES.read_text().splitlines() if n.strip()]
    assert len(names) >= 500
    failures = []
    for name in names:
        result = parse(name, reference_year=REFERENCE_YEAR)
        assert isinstance(result, ParseResult), name
        if result.failure_reason is FailureReason.INTERNAL_ERROR:
            failures.append(name)
        # every fixture name is well-formed enough to at least yield a title
        if not result.success:
            failures.append(name)
    assert not failures, f"{len(failures)} fixture names failed: {failures[:10]}"


@pytest.mark.req("FRG-IMP-021")
@pytest.mark.req("FRG-IMP-003")
@pytest.mark.skipif(
    not os.environ.get("FORAGERR_CORPUS_DIR"),
    reason="FORAGERR_CORPUS_DIR not set (mounted-library sweep is opt-in)",
)
def test_mounted_library_zero_crashes():
    root = os.environ["FORAGERR_CORPUS_DIR"]
    crashed = []
    internal = []
    count = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            if filename.startswith("."):
                continue  # resource forks / dotfiles
            count += 1
            try:
                result = parse(filename, reference_year=REFERENCE_YEAR)
            except Exception:  # the parse() contract forbids this entirely
                crashed.append(filename)
                continue
            assert isinstance(result, ParseResult)
            if result.failure_reason is FailureReason.INTERNAL_ERROR:
                internal.append(filename)
    assert count > 0, f"no files found under {root}"
    assert not crashed, f"{len(crashed)} names raised: {crashed[:10]}"
    assert not internal, (
        f"{len(internal)} names hit INTERNAL_ERROR: {internal[:10]}"
    )
