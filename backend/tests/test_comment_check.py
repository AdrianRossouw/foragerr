"""Comment-hygiene scanner (FRG-PROC-023).

Loads tools/comment_check.py by path (it lives outside the backend package,
next to tools/soup_check.py) and drives its pure `check(root)` against
synthetic tmp_path trees plus the real repository, never mutating the
repository's own files.

The fixture text below deliberately violates the standard it enforces; the
allowlist entry for this file is what keeps the scanner from flagging its
own test data.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_comment_check():
    spec = importlib.util.spec_from_file_location(
        "comment_check", REPO_ROOT / "tools" / "comment_check.py"
    )
    module = importlib.util.module_from_spec(spec)
    # Registered before exec: the module's dataclasses resolve their own
    # __module__ through sys.modules while the class body is being built.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


comment_check = _load_comment_check()


def rules_hit(findings) -> set[str]:
    return {f.rule for f in findings}


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """An empty non-git tree: discovery falls back to a filesystem walk, so
    nothing here depends on the repository's own git state."""
    return tmp_path


@pytest.mark.req("FRG-PROC-023")
def test_rig_specific_values_are_flagged(tree: Path):
    """A comment carrying a rig host:port, a private address or a home-directory
    path pins one environment — each is a distinct named rule so the report
    tells the author which neutrality rule was broken."""
    (tree / "mod.py").write_text(
        "# reachable on 127.0.0.1:8791 and 192.168.1.10\n"
        "# library lives under /Users/someone/comics\n"
        "VALUE = 1\n"
    )

    findings, _counts, _has_denylist = comment_check.check(tree)

    assert {"host-port", "private-ip", "local-path"} <= rules_hit(findings)
    assert all(f.path == "mod.py" for f in findings)
    assert {f.line for f in findings} == {1, 2}


@pytest.mark.req("FRG-PROC-023")
def test_documented_default_port_is_product_fact(tree: Path):
    """The port foragerr documents as its own default is a product value, not
    an environment value — the host:port rule must not fire on it, or the
    exception mechanism is useless and authors learn to ignore the tool."""
    port = sorted(comment_check.PRODUCT_PORTS)[0]
    (tree / "mod.py").write_text(f"# the app serves on localhost:{port} by default\n")

    findings, _counts, _has_denylist = comment_check.check(tree)

    assert findings == []


@pytest.mark.req("FRG-PROC-023")
def test_review_provenance_in_a_comment_is_flagged(tree: Path):
    """Rule 1: a comment records the constraint, not which review found it."""
    (tree / "mod.py").write_text("# drop the cached row here (Codex gate finding).\n")

    findings, _counts, _has_denylist = comment_check.check(tree)

    assert rules_hit(findings) == {"provenance"}


@pytest.mark.req("FRG-PROC-023")
def test_requirement_id_stating_the_constraint_is_accepted(tree: Path):
    """Rule 1 permits an FRG ID when the ID names the invariant; only
    review-process phrasing is a violation, so an invariant comment citing an
    ID — and prose about the review process in a process document — pass."""
    (tree / "mod.py").write_text(
        '"""Never suppress a single-issue wanted state (FRG-SER-019)."""\n'
        "\n"
        "# A collected edition may contain the issue but does not satisfy it:\n"
        "# no booktype predicate belongs in this query (FRG-SER-019).\n"
    )
    (tree / "notes.md").write_text("The gate review pass covers every angle.\n")

    findings, _counts, _has_denylist = comment_check.check(tree)

    assert findings == []


@pytest.mark.req("FRG-PROC-023")
def test_local_denylist_flags_operator_literals_anywhere(tree: Path):
    """A real collection title cannot be named by a committed pattern, so the
    gitignored local denylist carries it — and is matched against full file
    text, fixture literals included, not just comment text."""
    (tree / "tools").mkdir()
    (tree / "tools" / "comment_check_local_denylist.txt").write_text(
        "# one regex per line\nA Real Shelf Title\n"
    )
    (tree / "test_fixtures.py").write_text('SERIES = "A Real Shelf Title (2011)"\n')

    findings, counts, has_denylist = comment_check.check(tree)

    assert has_denylist is True
    assert [(f.path, f.line, f.rule) for f in findings] == [
        ("test_fixtures.py", 1, "local-denylist")
    ]
    assert counts["files"] >= 1


@pytest.mark.req("FRG-PROC-023")
def test_absent_local_denylist_does_not_fail_the_gate(tree: Path):
    """A fresh clone and CI have no local denylist: the generic pass still
    runs and decides the exit code, so a missing operator-private file can
    never be the reason a merge gate fails (or passes silently)."""
    (tree / "clean.py").write_text("# One writer holds the lock for the whole rename.\n")
    (tree / "dirty.py").write_text("# staged under /home/someone/incoming\n")

    clean_findings, _c, clean_has = comment_check.check(tree)
    assert clean_has is False
    assert rules_hit(clean_findings) == {"local-path"}
    assert comment_check.main([str(tree)]) == 1

    (tree / "dirty.py").unlink()
    findings, _counts, has_denylist = comment_check.check(tree)

    assert has_denylist is False
    assert findings == []
    assert comment_check.main([str(tree)]) == 0


@pytest.mark.req("FRG-PROC-023")
def test_allowlist_narrows_to_named_rules(tree: Path):
    """An allowlist entry exempts only the rules it names, so declaring one
    legitimate hit cannot silently license every other violation in the file."""
    (tree / "tools").mkdir()
    (tree / "tools" / "comment_check_allow.txt").write_text(
        "doc.md   local-path    # a portable shell recipe\n"
    )
    (tree / "doc.md").write_text("Run with /tmp/scratch on 127.0.0.1:8791.\n")

    findings, _counts, _has_denylist = comment_check.check(tree)

    assert rules_hit(findings) == {"host-port"}


@pytest.mark.req("FRG-PROC-023")
def test_code_is_not_scanned_only_its_non_product_text(tree: Path):
    """Scope is comments/docstrings/test names, never executable code: a
    scanner that rewrote string values used by logic would be unsafe to run
    as a gate."""
    (tree / "mod.py").write_text(
        'STAGING = "/tmp/staging"\n'
        'URL = "http://127.0.0.1:8791/api"\n'
        'LABEL = "gate finding"\n'
    )

    findings, _counts, _has_denylist = comment_check.check(tree)

    assert findings == []
