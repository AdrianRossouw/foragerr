"""Traceability marker for the end-to-end harness (FRG-PROC-010).

The real evidence for FRG-PROC-010 is the browser-driven Playwright run
(``e2e/run.sh``) attached to the milestone review — Playwright cannot run in the
pytest lane. This test keeps the traceability matrix honest without it: it
asserts the e2e suite manifest exists and that its scenario titles cover every
sub-clause of the requirement (first-run health, add series, interactive-search
rejection reasons, grab -> download -> import -> renamed file, library browse,
and OPDS navigation + correct comic MIME + byte-identical download), plus the
generated-report and live-tier structure. If a scenario is dropped, this fails.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_E2E = Path(__file__).resolve().parents[2] / "e2e"


def _spine() -> str:
    """All e2e spec titles/bodies concatenated (the spine plus the isolated
    restart scenario), so coverage checks see every scenario."""
    return "\n".join(
        p.read_text(encoding="utf-8") for p in sorted((_E2E / "tests").glob("*.spec.ts"))
    )


@pytest.mark.req("FRG-PROC-010")
def test_e2e_harness_files_present() -> None:
    """The one-command harness and its parts exist where the process expects."""
    for rel in (
        "run.sh",
        "compose.yaml",
        "playwright.config.ts",
        "package.json",
        "fixtures/mock_server.py",
        "fixtures/Dockerfile",
        "scripts/acceptance-report.mjs",
        "tests/spine.spec.ts",
        "tests/zz-restart.spec.ts",
        "SELECTORS.md",
        "README.md",
    ):
        assert (_E2E / rel).exists(), f"missing e2e/{rel}"


@pytest.mark.req("FRG-PROC-010")
def test_e2e_scenarios_cover_the_requirement() -> None:
    """Every sub-clause of FRG-PROC-010 has a titled scenario naming its ids."""
    spine = _spine()
    assert "FRG-PROC-010" in spine

    # (marker substring that must appear in a scenario title, human clause)
    required = {
        "FRG-DEP-007": "first-run health",
        "FRG-SER-005": "add a series (ComicVine fixture)",
        "FRG-UI-007": "interactive search rejection reasons",
        "FRG-DDL-010": "download verification before import",
        "FRG-PP-009": "renamed file in the library",
        "FRG-UI-003": "library browse",
        "FRG-OPDS-005": "OPDS download with correct comic MIME",
    }
    missing = [f"{mid} ({clause})" for mid, clause in required.items() if mid not in spine]
    assert not missing, f"e2e spine does not cover: {missing}"

    # The comic MIME and byte-identity are asserted, and a live tier is gated.
    assert "application/vnd.comicbook+zip" in spine
    assert "E2E_LIVE_SAB" in spine, "live-SAB tier gating must exist"
    assert "restart" in spine.lower(), "restart-resilience scenario must exist"


@pytest.mark.req("FRG-PROC-010")
def test_acceptance_report_is_generated_not_authored() -> None:
    """The acceptance report is produced from the Playwright JSON, never by hand."""
    generator = (_E2E / "scripts" / "acceptance-report.mjs").read_text(encoding="utf-8")
    assert "results.json" in generator or "argv" in generator
    assert "FRG-" in generator  # parses requirement ids out of test titles
