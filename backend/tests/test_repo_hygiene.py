"""Repository-side secret hygiene (FRG-DEP-005)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "backend" / "src"


def git_ignores(path: str) -> bool:
    return (
        subprocess.run(
            ["git", "-C", str(REPO_ROOT), "check-ignore", "-q", path],
            check=False,
        ).returncode
        == 0
    )


@pytest.mark.req("FRG-DEP-005")
def test_env_files_are_excluded_from_version_control():
    for candidate in (".env", ".env.local", "backend/.env", "backend/.env.production"):
        assert git_ignores(candidate), f"{candidate} is not gitignored"
    # the documented exception stays committable
    assert not git_ignores(".env.example")


@pytest.mark.req("FRG-DEP-005")
def test_no_secret_looking_literals_in_source():
    """No key/credential material assigned as a literal anywhere in backend/src."""
    pattern = re.compile(
        r"""(?ix)
        (api_?key|token|secret|password|passwd|credential)\w*   # key-shaped name
        \s*[:=]\s*
        ["'][A-Za-z0-9+/_\-]{8,}["']                            # non-trivial literal
        """
    )
    offenders = []
    for path in SRC_DIR.rglob("*.py"):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{path}:{lineno}: {line.strip()}")
    assert not offenders, "secret-shaped literals found:\n" + "\n".join(offenders)
