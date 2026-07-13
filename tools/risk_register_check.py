#!/usr/bin/env python3
"""Merge-gate validator for docs/security/risk-register.md (FRG-PROC-006).

Enforces the living-register discipline adopted in the 2026-07-13 living-docs
review: the register is a current-state document — every row leads with a
fixed-vocabulary status, carries no accreted history narration, and stays
scannable. History belongs to git. Mirrors tools/soup_check.py in spirit:
exit 0 = clean, non-zero with named violations otherwise.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REGISTER = Path(__file__).resolve().parent.parent / "docs" / "security" / "risk-register.md"

STATUS_WORDS = ("Mitigated", "Accepted", "Open", "Closed", "Withdrawn")
COLUMNS = 9  # ID | Description | STRIDE | Component | L | I | Status | Current mitigation | Source
ROW_CHAR_CEILING = 2200  # current worst ~1.6k; headroom without letting accretion back in

#: Accreted-narration tells: per-milestone status stamps and stacked bold markers.
NARRATION_RX = re.compile(r"\*\*(?:M\d+(?:/M\d+)? status|[a-z-]+ \(20\d\d-\d\d-\d\d\)\s*)\*\*")


def main() -> int:
    if not REGISTER.exists():
        print(f"risk_register_check: {REGISTER} not found", file=sys.stderr)
        return 2

    violations: list[str] = []
    rows = 0
    for n, line in enumerate(REGISTER.read_text().splitlines(), 1):
        if not line.startswith("| RISK-"):
            continue
        rows += 1
        rid = line.split("|")[1].strip()
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) != COLUMNS:
            violations.append(f"{rid} (line {n}): {len(cells)} columns, expected {COLUMNS}")
            continue
        status = cells[6]
        if not status.startswith(STATUS_WORDS):
            violations.append(
                f"{rid} (line {n}): Status cell must start with one of {STATUS_WORDS}, got: {status[:40]!r}"
            )
        stamps = len(re.findall(r"\b(Mitigated|Accepted|Open|Closed|Withdrawn)\b", status))
        if stamps > 1 and "residual" not in status:
            violations.append(
                f"{rid} (line {n}): Status cell carries {stamps} status words — one current state only"
            )
        if status.startswith("Accepted") and "Review trigger" not in cells[7]:
            violations.append(f"{rid} (line {n}): Accepted risk without a 'Review trigger' in its mitigation cell")
        if NARRATION_RX.search(line):
            violations.append(f"{rid} (line {n}): history-narration marker found — replace, don't append")
        if len(line) > ROW_CHAR_CEILING:
            violations.append(f"{rid} (line {n}): row is {len(line)} chars (> {ROW_CHAR_CEILING}) — compact it")

    if rows == 0:
        violations.append("no RISK rows found — register table missing or reformatted")

    if violations:
        print(f"risk_register_check: {len(violations)} violation(s) across {rows} rows:", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        return 1
    print(f"risk_register_check: {rows} rows clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
