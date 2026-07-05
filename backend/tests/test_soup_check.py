"""SOUP register vs. manifest drift check (FRG-PROC-012).

Loads tools/soup_check.py by path (it lives outside the backend package, next
to tools/trace.py) and exercises its pure `check(root)` function against both
the real, committed register and synthetic tmp_path copies -- never mutating
the repository's own files.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_soup_check():
    spec = importlib.util.spec_from_file_location(
        "soup_check", REPO_ROOT / "tools" / "soup_check.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


soup_check = _load_soup_check()


@pytest.mark.req("FRG-PROC-012")
def test_soup_check_passes_on_committed_register():
    """The committed register matches both manifests exactly -- check() must
    report zero problems against the real repository state. Once the frontend
    manifest exists (m1-ui-opds-deploy), its rows are covered too."""
    problems, counts, has_frontend = soup_check.check(REPO_ROOT)

    assert problems == []
    assert counts["backend runtime"] > 0
    assert counts["backend tooling"] > 0
    if has_frontend:
        assert counts["frontend runtime"] > 0
        assert counts["frontend tooling"] > 0


@pytest.fixture
def repo_copy(tmp_path: Path) -> Path:
    """A tmp_path copy of just the two files soup_check.py reads, so tests can
    freely mutate them without touching the real repository."""
    (tmp_path / "backend").mkdir()
    (tmp_path / "docs" / "security").mkdir(parents=True)
    shutil.copy(
        REPO_ROOT / "backend" / "pyproject.toml", tmp_path / "backend" / "pyproject.toml"
    )
    shutil.copy(
        REPO_ROOT / "docs" / "security" / "soup-register.md",
        tmp_path / "docs" / "security" / "soup-register.md",
    )
    return tmp_path


@pytest.mark.req("FRG-PROC-012")
def test_soup_check_passes_on_unmodified_copy(repo_copy: Path):
    """Sanity check: an untouched tmp_path copy of the real manifest/register
    pair is itself drift-free (isolates the fixture from the "does the real
    repo pass" assertion above)."""
    problems, _counts, _has_frontend = soup_check.check(repo_copy)

    assert problems == []


@pytest.mark.req("FRG-PROC-012")
def test_soup_check_detects_missing_register_row(repo_copy: Path):
    """Adding a dependency to pyproject.toml without a matching register row
    is drift: the manifest has an entry the register doesn't."""
    pyproject = repo_copy / "backend" / "pyproject.toml"
    text = pyproject.read_text()
    assert '"defusedxml>=0.7",' in text
    pyproject.write_text(
        text.replace(
            '"defusedxml>=0.7",',
            '"defusedxml>=0.7",\n    "totally-fake-soup-lib>=1.2.3",',
        )
    )

    problems, _counts, _has_frontend = soup_check.check(repo_copy)

    assert any("totally-fake-soup-lib" in p and "no register row" in p for p in problems)


@pytest.mark.req("FRG-PROC-012")
def test_soup_check_detects_constraint_mismatch(repo_copy: Path):
    """A register row whose version constraint no longer matches the manifest
    is drift, independent of the row/name existing on both sides."""
    register = repo_copy / "docs" / "security" / "soup-register.md"
    text = register.read_text()
    assert "| fastapi | `>=0.115` |" in text
    register.write_text(text.replace("| fastapi | `>=0.115` |", "| fastapi | `>=9.9` |"))

    problems, _counts, _has_frontend = soup_check.check(repo_copy)

    assert any("fastapi" in p and "constraint mismatch" in p for p in problems)


@pytest.mark.req("FRG-PROC-012")
def test_soup_check_detects_orphan_register_row(repo_copy: Path):
    """A register row for a dependency the manifest no longer declares is
    drift too (removed dependency, stale register row)."""
    pyproject = repo_copy / "backend" / "pyproject.toml"
    text = pyproject.read_text()
    assert '"defusedxml>=0.7",' in text
    pyproject.write_text(text.replace('    "defusedxml>=0.7",\n', ""))

    problems, _counts, _has_frontend = soup_check.check(repo_copy)

    assert any("defusedxml" in p and "not in the manifest" in p for p in problems)
