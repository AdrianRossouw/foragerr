"""Labelling-control checks for the public repository (FRG-DEP-014, FRG-PROC-014).

Once the repository is public, README.md is the labelling a reader trusts and
LICENSE is the grant they rely on. These tests pin the three license statements
(LICENSE file, pyproject declaration, README labelling) to each other so an
edit cannot let them drift apart, and hold the README to the labelling rules of
FRG-PROC-014 (resolvable traceability links, no stale private-tool
self-description, roadmap kept separate from shipped claims).
"""

import re
import tomllib
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.req("FRG-DEP-014")
def test_license_file_is_gpl3():
    text = (_ROOT / "LICENSE").read_text()
    assert "GNU GENERAL PUBLIC LICENSE" in text
    assert "Version 3, 29 June 2007" in text


@pytest.mark.req("FRG-DEP-014")
def test_pyproject_declares_gpl3():
    with open(_ROOT / "backend" / "pyproject.toml", "rb") as f:
        project = tomllib.load(f)["project"]
    assert project["license"] == "GPL-3.0-or-later", (
        "pyproject.toml [project].license must carry the SPDX expression "
        "matching the LICENSE file"
    )


@pytest.mark.req("FRG-DEP-014")
def test_readme_names_the_license_and_links_the_file():
    text = (_ROOT / "README.md").read_text()
    assert "GPL-3.0" in text, "README labelling must name the license"
    assert re.search(r"\[[^\]]*\]\(LICENSE\)", text), (
        "README must link the LICENSE file"
    )


def _readme():
    return (_ROOT / "README.md").read_text()


@pytest.mark.req("FRG-PROC-014")
def test_readme_relative_links_and_images_resolve():
    """Every relative link/image target in the README must exist in the repo.

    The screenshot walkthrough's promise is that a reader can walk
    screenshot → requirement → spec/manual; a broken path breaks the
    labelling, so link rot is a test failure.
    """
    broken = []
    for match in re.finditer(r"!?\[[^\]]*\]\(([^)#\s]+)\)", _readme()):
        target = match.group(1)
        if "://" in target:
            continue
        if not (_ROOT / target).exists():
            broken.append(target)
    assert not broken, f"README links to missing paths: {broken}"


@pytest.mark.req("FRG-PROC-014")
def test_readme_cited_requirement_ids_are_registered():
    registry = (
        _ROOT / "docs" / "traceability" / "requirements-registry.md"
    ).read_text()
    unregistered = {
        rid
        for rid in re.findall(r"FRG-[A-Z]+-\d{3}", _readme())
        if f"| {rid} |" not in registry
    }
    assert not unregistered, (
        f"README cites requirement IDs missing from the registry: "
        f"{sorted(unregistered)}"
    )


@pytest.mark.req("FRG-PROC-014")
def test_readme_walkthrough_screenshots_present():
    text = _readme()
    images = re.findall(r"!\[[^\]]*\]\((docs/readme-assets/[^)]+)\)", text)
    assert len(images) >= 5, (
        "the README walkthrough must embed the capture set from "
        "docs/readme-assets/"
    )
    for img in images:
        assert (_ROOT / img).stat().st_size <= 400_000, (
            f"{img} is too large for an in-repo README asset"
        )


@pytest.mark.req("FRG-PROC-015")
def test_history_scan_evidence_names_a_real_commit():
    """The pre-flip secret-scan evidence must exist and pin a scanned HEAD.

    The scan itself is a merge-gate step (network/tooling dependency); this
    test pins its paper trail: the evidence file records the tool, an
    explicit zero-unresolved statement, and a commit hash that actually
    exists in this repository's history.
    """
    evidence = (_ROOT / "docs" / "security" / "history-scan.md").read_text()
    assert "gitleaks" in evidence
    assert re.search(r"\*\*Unresolved findings\*\*: \*\*0\*\*", evidence)
    match = re.search(r"\*\*Scanned HEAD\*\*: `([0-9a-f]{40})`", evidence)
    assert match, "evidence must name the scanned HEAD commit"
    import subprocess

    proc = subprocess.run(
        ["git", "cat-file", "-e", f"{match.group(1)}^{{commit}}"],
        cwd=_ROOT,
        capture_output=True,
    )
    assert proc.returncode == 0, (
        f"scanned HEAD {match.group(1)} is not a commit in this repository"
    )


@pytest.mark.req("FRG-PROC-014")
def test_readme_has_roadmap_and_posture_and_no_private_framing():
    text = _readme()
    assert re.search(r"^## Roadmap", text, re.M), (
        "unshipped intentions belong under an explicit Roadmap heading"
    )
    assert "not solicited" in text, (
        "README must state the source-available contribution posture"
    )
    for path in ("README.md", "CLAUDE.md", "docs/manual/index.md", "CHANGELOG.md"):
        stale = (_ROOT / path).read_text().lower()
        assert "not released publicly" not in stale, path
        assert "never released" not in stale, path
        assert "a private," not in stale, path
