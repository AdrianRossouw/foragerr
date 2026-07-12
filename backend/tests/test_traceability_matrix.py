"""Traceability-matrix regeneration stability (FRG-PROC-005).

The matrix must be *regenerable* — which includes being STABLE: two runs over
the same repo state must produce the same bytes. `tools/trace.py` discovers
test files via ``Path.glob``, whose order is filesystem-dependent, so the
emitted per-requirement test list must be explicitly sorted (v0-6-3-fixes).
This pins the committed artifact's property rather than re-running the tool
(which would mutate a tracked file as a test side effect).
"""

from __future__ import annotations

from pathlib import Path

import pytest

MATRIX = Path(__file__).resolve().parents[2] / "docs" / "traceability" / "matrix.md"


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
