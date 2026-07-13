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

#: Accreted-narration tells. Per-milestone status stamps ("M1 status", bold or
#: not) are the historical accretion signature; two or more date stamps inside
#: the mitigation cell mean a timeline is being narrated (one date — e.g. an
#: owner-acceptance — is legitimate provenance). Free-prose narration without
#: markers is not mechanically detectable; the status-word and length checks
#: are the backstop for that.
NARRATION_RX = re.compile(r"\bM\d+(?:/M\d+)? status\b")
DATE_RX = re.compile(r"\(20\d\d-\d\d-\d\d[^)]*\)")
#: The Status cell must OPEN with exactly one vocabulary word at a word
#: boundary ("Mitigatedish" must not pass), and carry no second vocabulary
#: word. The one legitimate compound — a residual that was later closed —
#: is written lowercase ("residual closed <change>") and so never counts
#: as a second status word; there is deliberately NO substring exemption.
STATUS_RX = re.compile(r"^(?:%s)\b" % "|".join(STATUS_WORDS))


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
        # Escaped pipes (\|) are literal cell content, not delimiters.
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line)[1:-1]]
        rid = cells[0] if cells else line[:20]
        if len(cells) != COLUMNS:
            violations.append(f"{rid} (line {n}): {len(cells)} columns, expected {COLUMNS}")
            continue
        status = cells[6]
        if not STATUS_RX.match(status):
            violations.append(
                f"{rid} (line {n}): Status cell must start with one of {STATUS_WORDS}, got: {status[:40]!r}"
            )
        stamps = len(re.findall(r"\b(Mitigated|Accepted|Open|Closed|Withdrawn)\b", status))
        if stamps > 1:
            violations.append(
                f"{rid} (line {n}): Status cell carries {stamps} status words — one current state only"
            )
        if status.startswith("Accepted") and "Review trigger" not in cells[7]:
            violations.append(f"{rid} (line {n}): Accepted risk without a 'Review trigger' in its mitigation cell")
        if NARRATION_RX.search(line):
            violations.append(f"{rid} (line {n}): history-narration marker found — replace, don't append")
        if len(DATE_RX.findall(cells[7])) > 1:
            violations.append(
                f"{rid} (line {n}): multiple date stamps in the mitigation cell — reads as a narrated timeline"
            )
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
