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
