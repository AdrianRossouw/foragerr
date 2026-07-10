"""Consistency checks for the known-anomalies register (FRG-PROC-016) and the
KA-001 gitleaks detection-gap closure (FRG-PROC-015).

FRG-PROC-016 makes ``docs/security/known-anomalies.md`` a controlled document:
every accepted defect/deviation/exposure is a stable ``KA-NNN`` entry with a
fixed set of fields, IDs are never reused or renumbered, and KA-001 (the
exposed un-revocable ComicVine key) is present and Accepted. These tests pin
that structure so an edit cannot let the register drift.

The gitleaks test proves the ``bare-key-hex`` rule in the repo's
``.gitleaks.toml`` flags the exact KA-001 line shape (a bare ``KEY = '<hex>'``)
that the default ruleset missed. It runs the real gitleaks binary against a
synthetic fixture and skips (with a clear reason) when the binary is absent, so
the suite stays hermetic — the authoritative enforcement point is the
merge-gate history re-scan (commit-standard checklist item 7).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTER = REPO_ROOT / "docs" / "security" / "known-anomalies.md"
GITLEAKS_CONFIG = REPO_ROOT / ".gitleaks.toml"

# Required bold field labels every KA entry must carry (FRG-PROC-016).
REQUIRED_FIELDS = (
    "Description",
    "Location/scope",
    "Discovered",
    "Impact evaluation",
    "Owner decision",
    "Mitigations",
    "Review trigger",
    "Status",
)

KA_ID = re.compile(r"^KA-\d{3}$")

# A synthetic value reproducing the KA-001 line shape: a bare `KEY` identifier
# assigned a 40-char lowercase-hex literal ("a bad idea" x5). Deliberately fake;
# the real key value is never written anywhere in this repository.
SYNTHETIC_HEX = "abad1dea" * 5


def _entries() -> dict[str, str]:
    """Parse the register into {KA-NNN: section-body} by its ``## KA-`` headers."""
    text = REGISTER.read_text()
    entries: dict[str, str] = {}
    for match in re.finditer(r"^## (KA-\S+)[^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S):
        entries[match.group(1)] = match.group(2)
    return entries


@pytest.mark.req("FRG-PROC-016")
def test_register_exists_and_parses():
    assert REGISTER.exists(), "known-anomalies register must exist"
    entries = _entries()
    assert entries, "register must contain at least one KA-NNN entry"


@pytest.mark.req("FRG-PROC-016")
def test_ka_ids_are_wellformed_and_unique():
    text = REGISTER.read_text()
    heading_ids = re.findall(r"^## (KA-\S+)", text, re.M)
    for kid in heading_ids:
        assert KA_ID.match(kid), f"KA id {kid!r} must match ^KA-\\d{{3}}$"
    assert len(heading_ids) == len(set(heading_ids)), (
        f"KA ids must be unique (never reused/renumbered): {heading_ids}"
    )


@pytest.mark.req("FRG-PROC-016")
def test_every_entry_has_all_required_fields():
    for kid, body in _entries().items():
        for field in REQUIRED_FIELDS:
            assert re.search(rf"\*\*{re.escape(field)}\*\*", body), (
                f"{kid} is missing required bold field label **{field}**"
            )


@pytest.mark.req("FRG-PROC-016")
def test_ka_001_present_and_accepted():
    entries = _entries()
    assert "KA-001" in entries, "KA-001 (exposed ComicVine key) must be present"
    body = entries["KA-001"]
    assert re.search(r"\*\*Status\*\*:\s*Accepted", body), (
        "KA-001 must record Status: Accepted"
    )
    assert re.search(r"ComicVine", body), "KA-001 must name the ComicVine key exposure"


@pytest.mark.req("FRG-PROC-015")
def test_gitleaks_bare_key_hex_rule_flags_ka001_shape():
    """The repo's .gitleaks.toml bare-key-hex rule must flag a bare `KEY = '<hex>'`.

    Skips when the gitleaks binary is unavailable so the suite stays hermetic;
    the merge-gate re-scan (commit-standard item 7) is the enforcement point.
    """
    binary = os.environ.get("GITLEAKS_BIN") or shutil.which("gitleaks")
    if binary is None or not os.access(binary, os.X_OK):
        pytest.skip(
            "gitleaks binary unavailable (set GITLEAKS_BIN or add to PATH) — "
            "merge-gate re-scan is authoritative"
        )
    assert GITLEAKS_CONFIG.exists(), ".gitleaks.toml must exist at repo root"

    with tempfile.TemporaryDirectory() as tmp:
        scan_dir = Path(tmp)
        (scan_dir / "synthetic.html").write_text(
            "class Foo {\n  KEY = '" + SYNTHETIC_HEX + "';\n}\n"
        )
        report = scan_dir / "report.json"
        proc = subprocess.run(
            [
                binary,
                "dir",
                str(scan_dir),
                "--config",
                str(GITLEAKS_CONFIG),
                "--no-banner",
                "--report-format",
                "json",
                "--report-path",
                str(report),
            ],
            capture_output=True,
            text=True,
        )
        # gitleaks exits 1 when leaks are found — that is the expected outcome.
        assert report.exists(), f"gitleaks produced no report (stderr: {proc.stderr})"
        findings = json.loads(report.read_text())
        rule_ids = {f["RuleID"] for f in findings}
        assert "bare-key-hex" in rule_ids, (
            f"bare-key-hex rule did not flag the synthetic KA-001 line shape; "
            f"rules fired: {sorted(rule_ids)}"
        )
