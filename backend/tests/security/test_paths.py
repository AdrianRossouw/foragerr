"""safe_join confinement + relocated component sanitizer (FRG-SEC-004).

The traversal corpus is generated with seeded stdlib ``random`` (this repo's
property-testing convention — see ``tests/parser/test_fuzz.py`` — no third-party
property-testing dependency): every hostile path part must either sanitize to a
path that realpath-confirms *inside* the managed root, or be refused with a
:class:`PathConfinementError` — in no case may a constructed path escape.
"""

from __future__ import annotations

import os
import random

import pytest

from foragerr.security.paths import (
    PathConfinementError,
    safe_join,
    safe_path_component,
)

SEED = 20260705


def _is_inside(root, path) -> bool:
    root_real = os.path.realpath(root)
    path_real = os.path.realpath(path)
    if path_real == root_real:
        return True
    try:
        return os.path.commonpath([root_real, path_real]) == root_real
    except ValueError:
        return False


# --- safe_join: sanctioned destination constructor ---------------------------


@pytest.mark.req("FRG-SEC-004")
def test_safe_join_builds_expected_path_under_root(tmp_path):
    dest = safe_join(tmp_path, "Saga (2012)", "Saga 001 (2012) [__123__].cbz")
    assert dest == tmp_path / "Saga (2012)" / "Saga 001 (2012) [__123__].cbz"
    assert _is_inside(tmp_path, dest)


@pytest.mark.req("FRG-SEC-004")
@pytest.mark.parametrize(
    "part",
    [
        "../../etc/passwd",
        "..",
        "../..",
        "foo/../../bar",
        "..\\..\\windows",
        "/etc/passwd",
        "C:\\Windows\\System32",
        "CON",
        "NUL.txt",
        "trailing...",
        "  leading",
        "a\x00b",
        "homoglyph⁄slash",  # unicode fraction slash — not an OS separator
        "⧸big-solidus",
    ],
)
def test_safe_join_traversal_corpus_never_escapes(tmp_path, part):
    dest = safe_join(tmp_path, part, "issue.cbz")
    # No refusal is expected for these (they sanitize), but if one were, it
    # would raise rather than escape — either way the invariant holds.
    assert _is_inside(tmp_path, dest)
    # The sanitized first component introduced no directory boundary.
    first = dest.relative_to(tmp_path).parts[0]
    assert first not in ("", ".", "..")
    assert not first.startswith("..")


@pytest.mark.req("FRG-SEC-004")
def test_safe_join_fuzz_corpus_confined(tmp_path):
    rng = random.Random(SEED)
    alphabet = "../\\.:CONUL abc⁄∕\x00\x1f. "
    for _ in range(3000):
        parts = [
            "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 24)))
            for _ in range(rng.randint(1, 4))
        ]
        try:
            dest = safe_join(tmp_path, *parts)
        except PathConfinementError:
            continue  # refused-with-reason is an acceptable outcome
        assert _is_inside(tmp_path, dest), (parts, dest)


@pytest.mark.req("FRG-SEC-004")
def test_safe_join_refuses_escape_through_a_preexisting_symlink(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    # An attacker-planted symlink already sitting inside the root, pointing out.
    link = root / "escape"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")
    with pytest.raises(PathConfinementError):
        safe_join(root, "escape", "loot.cbz")


@pytest.mark.req("FRG-SEC-004")
def test_safe_join_output_is_writable_inside_root(tmp_path):
    dest = safe_join(tmp_path, "Series (2020)", "file.cbz")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"data")
    assert dest.read_bytes() == b"data"
    assert _is_inside(tmp_path, dest)


# --- relocated component sanitizer under single ownership --------------------


@pytest.mark.req("FRG-SEC-004")
def test_component_sanitizer_is_owned_here(tmp_path):
    # The one implementation lives in security.paths; library.paths must not
    # expose a second, independently importable copy.
    import foragerr.library.paths as lib_paths

    assert not hasattr(lib_paths, "safe_path_component")
    assert safe_path_component("../../etc/passwd") not in ("", "..", ".")
    assert "/" not in safe_path_component("a/b/c")
