"""Traceability-matrix regeneration stability (FRG-PROC-005).

The matrix must be *regenerable* — which includes being STABLE: two runs over
the same repo state must produce the same bytes. `tools/trace.py` discovers
test files via ``Path.glob``, whose order is filesystem-dependent, so the
emitted per-requirement test list must be explicitly sorted (v0-6-3-fixes).
This pins the committed artifact's property rather than re-running the tool
(which would mutate a tracked file as a test side effect).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "docs" / "traceability" / "matrix.md"

_spec = importlib.util.spec_from_file_location("trace_tool", ROOT / "tools" / "trace.py")
trace_tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(trace_tool)


@pytest.mark.req("FRG-PROC-005")
def test_matrix_test_cells_are_sorted():
    rows = [
        line
        for line in MATRIX.read_text().splitlines()
        if line.startswith("| FRG-")
    ]
    assert rows, "matrix has no requirement rows — regenerate it"
    unsorted_cells = []
    for line in rows:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        tests_cell = cells[4]
        if tests_cell == "—":
            continue
        files = [t.strip() for t in tests_cell.split(",")]
        if files != sorted(files):
            unsorted_cells.append(cells[0])
    assert not unsorted_cells, (
        "matrix Tests cells are not sorted (regenerated with a pre-fix "
        f"tools/trace.py?): {unsorted_cells}"
    )


@pytest.mark.req("FRG-PROC-005")
def test_pre_baseline_statuses_are_excused_only_in_open_deltas():
    """An approved (or proposed) registry row with no baseline spec is a gap
    UNLESS it lives in an open change delta (FRG-PROC-009 approval gate). Pins
    the widened exemption so a regression that reverts it is caught here, not at
    the next merge gate."""
    assert trace_tool.PRE_BASELINE_STATUSES == ("proposed", "approved")
    # Every currently-approved FRG-SITE row is backed by the open change delta,
    # so trace.py must run clean over real repo state (the same check the merge
    # gate runs). A regression narrowing the status set would surface those rows
    # as gaps and make main() exit non-zero.
    reg = trace_tool.registry_rows()
    delta_ids = trace_tool.open_change_delta_ids()
    approved_site = [rid for rid, row in reg.items()
                     if rid.startswith("FRG-SITE-") and row["status"] == "approved"]
    assert approved_site, "expected the site change's approved rows to be present"
    for rid in approved_site:
        assert rid in delta_ids, f"{rid} approved but not in any open change delta"
