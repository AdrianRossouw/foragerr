"""Labelling-control checks for the public repository (FRG-DEP-014, FRG-PROC-014).

Once the repository is public, README.md is the labelling a reader trusts and
LICENSE is the grant they rely on. These tests pin the three license statements
(LICENSE file, pyproject declaration, README labelling) to each other so an
edit cannot let them drift apart, and hold the README to the labelling rules of
FRG-PROC-014: resolvable traceability links, tour captions that cite the right
spec area for each requirement, shipped-only feature claims outside the
Roadmap, and no stale private-tool self-description anywhere in the controlled
documents. Registry parsing is delegated to tools/trace.py (loaded by path,
like tools/soup_check.py in test_soup_check.py) so this file and the matrix
generator can never disagree about what counts as a registered row.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_trace():
    spec = importlib.util.spec_from_file_location(
        "trace", REPO_ROOT / "tools" / "trace.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REGISTRY = _load_trace().registry_rows()


def _readme() -> str:
    return (REPO_ROOT / "README.md").read_text()


@pytest.mark.req("FRG-DEP-014")
def test_license_file_is_gpl3():
    text = (REPO_ROOT / "LICENSE").read_text()
    assert "GNU GENERAL PUBLIC LICENSE" in text
    assert "Version 3, 29 June 2007" in text


@pytest.mark.req("FRG-DEP-014")
def test_pyproject_declares_gpl3():
    with open(REPO_ROOT / "backend" / "pyproject.toml", "rb") as f:
        project = tomllib.load(f)["project"]
    assert project["license"] == "GPL-3.0-or-later", (
        "pyproject.toml [project].license must carry the SPDX expression "
        "matching the LICENSE file"
    )


@pytest.mark.req("FRG-DEP-014")
def test_readme_names_the_license_and_links_the_file():
    text = _readme()
    assert "GPL-3.0-or-later" in text, (
        "README labelling must name the exact SPDX expression pyproject "
        "declares — the two grants must agree (FRG-DEP-014)"
    )
    assert re.search(r"\[[^\]]*\]\(LICENSE\)", text), (
        "README must link the LICENSE file"
    )


@pytest.mark.req("FRG-PROC-014")
def test_readme_relative_links_and_images_resolve():
    """Every relative link/image target in the README must exist in the repo.

    The tour's promise is that a reader can walk screenshot → requirement →
    spec/manual; a broken path breaks the labelling, so link rot is a test
    failure.
    """
    broken = []
    for match in re.finditer(r"!?\[[^\]]*\]\(([^)#\s]+)\)", _readme()):
        target = match.group(1)
        if "://" in target:
            continue
        if not (REPO_ROOT / target).exists():
            broken.append(target)
    assert not broken, f"README links to missing paths: {broken}"


@pytest.mark.req("FRG-PROC-014")
def test_readme_cited_requirement_ids_are_registered():
    unregistered = {
        rid
        for rid in re.findall(r"FRG-[A-Z]+-\d{3}", _readme())
        if rid not in REGISTRY
    }
    assert not unregistered, (
        f"README cites requirement IDs missing from the registry: "
        f"{sorted(unregistered)}"
    )


def _tour_sections() -> dict[str, str]:
    """The '## A tour…' subsections of the README, name → body."""
    text = _readme()
    tour = re.search(r"^## A tour.*?(?=^## )", text, re.M | re.S)
    assert tour, "README must keep the tour section (FRG-PROC-014 walkthrough)"
    return {
        m.group(1).strip(): m.group(2)
        for m in re.finditer(r"^### (.+?)\n(.*?)(?=^### |\Z)", tour.group(0), re.M | re.S)
    }


@pytest.mark.req("FRG-PROC-014")
def test_tour_screenshots_are_tracked_and_bounded():
    images = re.findall(r"!\[[^\]]*\]\((docs/readme-assets/[^)]+)\)", _readme())
    assert len(images) >= 5, (
        "the README tour must embed the capture set from docs/readme-assets/"
    )
    tracked = set(
        subprocess.run(
            ["git", "ls-files", "docs/readme-assets"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        ).stdout.split()
    )
    for img in images:
        assert img in tracked, f"{img} is referenced but not tracked by git"
        assert (REPO_ROOT / img).stat().st_size <= 300_000, (
            f"{img} exceeds the ~300 KB in-repo asset budget (design "
            f"decision 3 of the going-public change)"
        )


@pytest.mark.req("FRG-PROC-014")
def test_tour_captions_cite_implemented_ids_with_matching_spec_area():
    """Mechanizes the FRG-PROC-014 'shipped claims only' + traceability pair.

    Every requirement a tour caption cites must be implemented (a tour screen
    is a shipped-behavior claim; unshipped work belongs under Roadmap), and
    the spec file(s) the same caption links must include the area the
    registry assigns to each cited ID — catching copy-paste caption mixups.
    """
    for name, body in _tour_sections().items():
        ids = set(re.findall(r"FRG-[A-Z]+-\d{3}", body))
        areas_linked = set(re.findall(r"openspec/specs/([a-z-]+)/spec\.md", body))
        assert ids, f"tour section {name!r} cites no requirement IDs"
        for rid in ids:
            row = REGISTRY.get(rid)
            assert row, f"tour section {name!r} cites unregistered {rid}"
            assert row["status"] in ("implemented", "verified"), (
                f"tour section {name!r} presents {rid} as shipped but the "
                f"registry says {row['status']!r} — unshipped work belongs "
                f"under Roadmap"
            )
            assert row["spec"] in areas_linked, (
                f"tour section {name!r} cites {rid} (area {row['spec']!r}) "
                f"but links spec areas {sorted(areas_linked)}"
            )


@pytest.mark.req("FRG-PROC-015")
def test_history_scan_evidence_names_a_real_commit():
    """The pre-flip secret-scan evidence must exist and pin a scanned HEAD.

    The scan itself is a merge-gate step (network/tooling dependency); this
    test pins its paper trail: the evidence file records the tool, an
    explicit zero-unresolved statement, and a commit hash that actually
    exists in this repository's history.
    """
    evidence = (REPO_ROOT / "docs" / "security" / "history-scan.md").read_text()
    assert "gitleaks" in evidence
    assert re.search(r"\*\*Unresolved findings\*\*: \*\*0\*\*", evidence)
    match = re.search(r"\*\*Scanned HEAD\*\*: `([0-9a-f]{40})`", evidence)
    assert match, "evidence must name the scanned HEAD commit"

    shallow = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if shallow.stdout.strip() == "true":
        pytest.skip("shallow clone: scanned-HEAD ancestry is not checkable")
    proc = subprocess.run(
        ["git", "merge-base", "--is-ancestor", match.group(1), "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    assert proc.returncode == 0, (
        f"scanned HEAD {match.group(1)} is not an ancestor-or-equal of HEAD — "
        f"the evidence does not cover this history (design decision 5, "
        f"going-public change)"
    )


@pytest.mark.req("FRG-PROC-014")
def test_no_private_framing_in_controlled_documents():
    text = _readme()
    roadmap = re.search(r"^## Roadmap\b.*?(?=^## )", text, re.M | re.S)
    assert roadmap, (
        "unshipped intentions belong under an explicit Roadmap heading"
    )
    assert re.search(r"\]\(docs/roadmap\.md\)", roadmap.group(0)), (
        "the README Roadmap section must link to docs/roadmap.md (the single "
        "home for forward-looking content) rather than restate unshipped plans "
        "(FRG-PROC-014, FRG-PROC-018)"
    )
    assert "not solicited" in text, (
        "README must state the source-available contribution posture"
    )
    controlled = [
        REPO_ROOT / "README.md",
        REPO_ROOT / "CLAUDE.md",
        REPO_ROOT / "CHANGELOG.md",
        *sorted((REPO_ROOT / "docs" / "manual").rglob("*.md")),
    ]
    stale_phrases = (
        "not released publicly",
        "never released",
        "a private,",
        "private tool",
        "developed privately",
    )
    for path in controlled:
        lowered = path.read_text().lower()
        for phrase in stale_phrases:
            assert phrase not in lowered, (
                f"{path.relative_to(REPO_ROOT)} still carries stale private "
                f"framing: {phrase!r}"
            )


@pytest.mark.req("FRG-PROC-011")
def test_roadmap_milestone_labels_match_the_registry():
    """docs/roadmap.md items citing an FRG ID must carry the registry's
    milestone — a roadmap reshape that forgets the roadmap document (or vice
    versa) fails here instead of shipping a stale public claim. Retargeted
    from the README by roadmap-single-source (FRG-PROC-018): the README no
    longer restates roadmap entries."""
    text = (REPO_ROOT / "docs" / "roadmap.md").read_text()
    sections = re.split(r"^## ", text, flags=re.M)[1:]
    checked = 0
    for section in sections:
        heading = section.splitlines()[0]
        milestone_token = re.search(r"\bM\d+\b", heading)
        if not milestone_token:
            continue
        milestone = milestone_token.group(0)
        for rid in re.findall(r"FRG-[A-Z]+-\d{3}", section):
            row = REGISTRY.get(rid)
            assert row and row["milestone"] == milestone, (
                f"docs/roadmap.md labels {rid} as {milestone} but the registry "
                f"says {row['milestone'] if row else 'UNREGISTERED'}"
            )
            checked += 1
    assert checked, (
        "expected docs/roadmap.md to cite at least one FRG id under a "
        "milestone heading — the parser or the roadmap layout changed"
    )
