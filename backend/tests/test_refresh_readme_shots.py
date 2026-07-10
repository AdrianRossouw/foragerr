"""Structural checks for the README-screenshot refresh tool (FRG-PROC-017).

The tool (`tools/refresh-readme-shots.sh`) regenerates the README tour's
screenshots by running the app against the demo library and driving the
committed capture script. Actually running it needs the demo library + a
browser and is a merge-gate step; these tests are the hermetic pin (same
test-vs-gate split as the history scan in ``test_public_labelling.py``): they
verify the tool exists and is executable, and that the README's embedded
assets exactly match the capture script's shot set — without the demo library
or a browser.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL = REPO_ROOT / "tools" / "refresh-readme-shots.sh"
CAPTURE = REPO_ROOT / "e2e" / "scripts" / "capture-readme-shots.ts"
README = REPO_ROOT / "README.md"


def _capture_shot_ids() -> set[str]:
    """The shot ids the capture script declares (``id: '<id>'``)."""
    return set(re.findall(r"id:\s*'([a-z0-9-]+)'", CAPTURE.read_text()))


def _readme_shot_ids() -> set[str]:
    """The README's embedded ``docs/readme-assets/<id>.png`` basenames."""
    return {
        Path(m).stem
        for m in re.findall(r"docs/readme-assets/([^)\s]+\.png)", README.read_text())
    }


@pytest.mark.req("FRG-PROC-017")
def test_refresh_tool_exists_and_is_executable():
    assert TOOL.is_file(), "tools/refresh-readme-shots.sh must exist"
    assert os.access(TOOL, os.X_OK), "the refresh tool must be executable"


@pytest.mark.req("FRG-PROC-017")
def test_refresh_tool_drives_the_committed_capture_script():
    text = TOOL.read_text()
    assert "capture-readme-shots.ts" in text, (
        "the tool must drive the committed capture script"
    )
    # The optimize/verify contract: a budget bound and a non-zero exit path.
    assert "300000" in text or "SHOT_BUDGET" in text
    assert re.search(r"exit 1|fail ", text), (
        "the tool must exit non-zero when a shot is missing or over budget"
    )


@pytest.mark.req("FRG-PROC-017")
def test_refresh_tool_guards_against_a_stale_port():
    """A pre-existing instance on the port must be refused unless explicitly reused."""
    text = TOOL.read_text()
    # Probes the health endpoint before starting its own backend…
    assert re.search(r'curl -fsS "\$\{BASE_URL\}/health".*\n.*FORAGERR_REFRESH_REUSE', text), (
        "the tool must probe ${BASE_URL}/health and honour FORAGERR_REFRESH_REUSE"
    )
    # …and either reuses (opt-in) or fails loudly.
    assert "FORAGERR_REFRESH_REUSE" in text
    assert re.search(r"already serving.*fail|fail .*already serving", text) or (
        "already serving" in text
    ), "the tool must fail when the port is already in use"


@pytest.mark.req("FRG-PROC-017")
def test_refresh_tool_fails_on_incomplete_import():
    """A staged group with no ComicVine proposal must abort the tour, not ship partial."""
    text = TOOL.read_text()
    assert "proposedCvVolumeId" in text, (
        "the tool must inspect each staged group's ComicVine proposal"
    )
    assert re.search(r"UNPROPOSED", text), (
        "the tool must collect the unproposed groups"
    )
    assert re.search(r"lack a ComicVine proposal", text), (
        "the tool must fail listing the unproposed group names"
    )


@pytest.mark.req("FRG-PROC-017")
def test_readme_embeds_exactly_the_capture_shot_set():
    capture = _capture_shot_ids()
    readme = _readme_shot_ids()
    assert capture, "the capture script must declare a shot set"
    assert capture == readme, (
        f"README embedded assets {sorted(readme)} must exactly match the "
        f"capture script's shot set {sorted(capture)}"
    )


@pytest.mark.req("FRG-PROC-017")
def test_capture_shot_assets_are_tracked_and_within_budget():
    """Each declared shot has a committed, in-budget asset on disk."""
    for shot in _capture_shot_ids():
        asset = REPO_ROOT / "docs" / "readme-assets" / f"{shot}.png"
        assert asset.is_file(), f"{asset} is declared by the capture script but missing"
        assert asset.stat().st_size <= 300_000, (
            f"{asset.name} exceeds the ~300 KB in-repo asset budget"
        )
