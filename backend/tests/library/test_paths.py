"""Safe path components, series path template, and rename-with-rollback
(FRG-SER-008, FRG-NFR-012)."""

from __future__ import annotations

import os
import stat

import pytest

from foragerr.library.paths import (
    PathNotUnderRootError,
    build_series_path,
    rename_series_directory,
    safe_path_component,
    series_folder_name,
    validate_under_root,
)


@pytest.mark.req("FRG-NFR-012")
@pytest.mark.parametrize(
    "raw",
    [
        "../../etc/passwd",
        "..",
        "../..",
        "foo/../../bar",
        "..\\..\\windows",
        "/etc/passwd",
        "C:\\Windows\\System32",
    ],
)
def test_traversal_and_absolute_sequences_cannot_escape_a_component(raw):
    safe = safe_path_component(raw)
    assert "/" not in safe
    assert "\\" not in safe
    assert safe not in ("", ".", "..")
    assert not safe.startswith("..")


@pytest.mark.req("FRG-NFR-012")
@pytest.mark.parametrize(
    "raw", ["CON", "PRN", "AUX", "NUL", "COM1", "LPT1", "con.txt", "Con.tar.gz"]
)
def test_reserved_windows_device_names_are_de_reserved(raw):
    safe = safe_path_component(raw)
    stem = safe.split(".", 1)[0].upper()
    reserved = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {
        f"LPT{i}" for i in range(1, 10)
    }
    assert stem not in reserved


@pytest.mark.req("FRG-NFR-012")
def test_trailing_dots_and_spaces_are_stripped():
    assert safe_path_component("Batman.  ") == "Batman"
    assert safe_path_component("  .Batman") == "Batman"


@pytest.mark.req("FRG-NFR-012")
def test_empty_or_pure_separator_input_falls_back():
    assert safe_path_component("") == "untitled"
    assert safe_path_component("   ") == "untitled"
    assert safe_path_component("///") == "untitled"


@pytest.mark.req("FRG-NFR-012")
def test_legitimate_titles_pass_through_unchanged():
    assert safe_path_component("Saga") == "Saga"
    assert safe_path_component("X-Men: Legacy") == "X-Men: Legacy"


@pytest.mark.req("FRG-SER-008")
def test_default_path_uses_the_fixed_template(tmp_path):
    root = tmp_path / "comics"
    path = build_series_path(root, "Saga", 2012)
    assert path == root / "Saga (2012)"


@pytest.mark.req("FRG-SER-008")
def test_template_sanitizes_a_hostile_title(tmp_path):
    root = tmp_path / "comics"
    name = series_folder_name("../../etc/Saga", 2012)
    assert "/" not in name
    assert ".." not in name.split(" (")[0].strip()


@pytest.mark.req("FRG-SER-008")
def test_path_under_registered_root_validates(tmp_path):
    root = tmp_path / "comics"
    root.mkdir()
    candidate = root / "Saga (2012)"
    resolved = validate_under_root(candidate, [root])
    assert resolved == candidate.resolve()


@pytest.mark.req("FRG-SER-008")
def test_path_outside_every_root_is_rejected(tmp_path):
    root = tmp_path / "comics"
    root.mkdir()
    outside = tmp_path / "elsewhere" / "Saga"
    with pytest.raises(PathNotUnderRootError):
        validate_under_root(outside, [root])


@pytest.mark.req("FRG-SER-008")
def test_valid_path_change_renames_the_directory(tmp_path):
    root = tmp_path / "comics"
    root.mkdir()
    old = root / "Saga (2012)"
    old.mkdir()
    (old / "issue-1.cbz").write_bytes(b"data")
    new = root / "Saga Renamed (2012)"

    rename_series_directory(old, new)

    assert not old.exists()
    assert (new / "issue-1.cbz").read_bytes() == b"data"


@pytest.mark.req("FRG-SER-008")
def test_failed_rename_can_be_rolled_back_by_the_caller(tmp_path):
    root = tmp_path / "comics"
    root.mkdir()
    old = root / "Saga (2012)"
    old.mkdir()
    new = root / "Saga Renamed (2012)"

    # Simulate a filesystem-level failure (e.g. permission denied) by making
    # the parent directory read-only so os.rename's target creation fails.
    old_mode = stat.S_IMODE(os.stat(root).st_mode)
    os.chmod(root, stat.S_IREAD | stat.S_IEXEC)
    try:
        with pytest.raises(OSError):
            rename_series_directory(old, new)
    finally:
        os.chmod(root, old_mode)

    # The directory (and its identity) stayed exactly where it was — a
    # caller doing this inside write_session() would let the row-update
    # rollback happen naturally alongside this untouched disk state.
    assert old.exists()
    assert not new.exists()
