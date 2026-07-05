"""No self-update mechanism exists; version is fixed at runtime
(FRG-DEP-009 — deliberate divergence from Mylar's git/tarball self-update)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from foragerr.app import create_app
from foragerr.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "backend" / "src"

#: Actual self-update APIs/constructs — not the words used in prose/comments
#: discussing the divergence (this module's own docstrings say "self-update"
#: and "version check" while explaining why neither exists; matching bare
#: words would flag our own documentation).
_SELF_UPDATE_PATTERNS = [
    re.compile(r"\bgit\.(Repo|clone_from)\b"),
    re.compile(r"\bsubprocess\.\w+\([^)]*[\"']git[\"']"),
    re.compile(r"\bGitPython\b"),
    re.compile(r"\btarfile\.(open|TarFile)\b"),
    re.compile(r"\bshutil\.unpack_archive\b"),
    re.compile(r"\burllib\.request\.urlretrieve\b"),
    re.compile(r"\bos\.exec[lv][ep]?\("),
]


@pytest.mark.req("FRG-DEP-009")
def test_no_self_update_code_path_exists():
    offenders = []
    for path in sorted(SRC_DIR.rglob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for pattern in _SELF_UPDATE_PATTERNS:
                if pattern.search(line):
                    offenders.append(
                        f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}"
                    )
    assert not offenders, (
        "self-update machinery found (FRG-DEP-009 divergence violated):\n"
        + "\n".join(offenders)
    )


@pytest.mark.req("FRG-DEP-009")
def test_no_update_route_or_config_setting(tmp_path):
    path = tmp_path / "cfg"
    path.mkdir()
    app = create_app(Settings(config_dir=path))
    offending_routes = [
        route.path
        for route in app.routes
        if hasattr(route, "path") and "update" in route.path.lower()
    ]
    assert not offending_routes
    assert not any("update" in name.lower() for name in Settings.model_fields)


@pytest.mark.req("FRG-DEP-009")
def test_version_is_fixed_for_the_lifetime_of_the_process():
    """Calling the version resolver repeatedly (as the process would over its
    lifetime) never changes the reported value — there is no code path that
    could mutate it at runtime."""
    from foragerr.api.system import build_info

    first = build_info()
    second = build_info()
    assert first == second
