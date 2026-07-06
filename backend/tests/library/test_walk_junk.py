"""Shared-walk junk rules, depth bound, and race tolerance (FRG-IMP-022).

``iter_archive_files`` is the ONE walk every intake uses (series scan, rescan,
manual import, library import), so the junk rules live inside it and every
consumer inherits them — these tests pin the walk directly.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from foragerr.library import matching
from foragerr.parser.vocab import ARCHIVE_EXTENSIONS


def _touch(path: Path, content: bytes = b"comicbytes") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


@pytest.mark.req("FRG-IMP-022")
def test_junk_tree_yields_exactly_the_real_archives(tmp_path: Path):
    """AppleDouble/@eaDir dirs, ``._`` forks, dotfiles, zero-byte files, and
    unpack-temp folders are all skipped; an UPPERCASE extension is recognized."""
    root = tmp_path / "library"
    real_lower = _touch(root / "Saga (2012)" / "Saga 001 (2012).cbz")
    real_upper = _touch(root / "Saga (2012)" / "Saga 002 (2012).CBZ")

    # Junk files alongside the real archives.
    _touch(root / "Saga (2012)" / "._Saga 001 (2012).cbz")  # resource fork
    _touch(root / "Saga (2012)" / ".hidden.cbz")  # dotfile
    _touch(root / "Saga (2012)" / "empty.cbz", b"")  # zero-byte
    # Junk directories that must never be descended into.
    _touch(root / "@eaDir" / "thumb.cbz")
    _touch(root / ".AppleDouble" / "Saga 001 (2012).cbz")
    _touch(root / "_UNPACK_Saga.003" / "Saga 003 (2012).cbz")
    _touch(root / "Saga (2012)" / "_unpack_tmp" / "partial.cbz")

    found = matching.iter_archive_files(str(root), ARCHIVE_EXTENSIONS)

    assert sorted(path for path, _size in found) == sorted(
        [str(real_lower), str(real_upper)]
    )


@pytest.mark.req("FRG-IMP-022")
def test_junk_predicates_direct():
    assert matching.is_junk_dir("@eaDir")
    assert matching.is_junk_dir(".AppleDouble")
    assert matching.is_junk_dir("_UNPACK_Some.Release")
    assert matching.is_junk_dir("_unpack_tmp")
    assert not matching.is_junk_dir("Saga (2012)")
    assert not matching.is_junk_dir("Undertow (2014)")  # no false _unpack prefix

    assert matching.is_junk_file("._fork.cbz", 100)
    assert matching.is_junk_file(".hidden.cbz", 100)
    assert matching.is_junk_file("empty.cbz", 0)
    assert not matching.is_junk_file("Saga 001.cbz", 100)


@pytest.mark.req("FRG-IMP-022")
def test_zero_byte_single_file_root_yields_nothing(tmp_path: Path):
    empty = _touch(tmp_path / "empty.cbz", b"")
    assert matching.iter_archive_files(str(empty), ARCHIVE_EXTENSIONS) == []


@pytest.mark.req("FRG-IMP-022")
def test_walk_stops_at_the_depth_bound(tmp_path: Path):
    root = tmp_path / "library"
    shallow = _touch(root / "a" / "one.cbz")
    _touch(root / "a" / "b" / "c" / "too-deep.cbz")

    found = matching.iter_archive_files(str(root), ARCHIVE_EXTENSIONS, max_depth=2)

    assert [path for path, _size in found] == [str(shallow)]


@pytest.mark.req("FRG-IMP-022")
def test_entry_vanishing_mid_walk_is_skipped_not_fatal(tmp_path: Path, monkeypatch):
    """A file that disappears between listing and stat is skipped silently."""
    root = tmp_path / "library"
    survivor = _touch(root / "s" / "keeper 001.cbz")
    doomed = _touch(root / "s" / "doomed 001.cbz")

    real_getsize = os.path.getsize

    def racing_getsize(path):
        if str(path) == str(doomed):
            raise OSError(2, "vanished mid-walk", str(path))
        return real_getsize(path)

    monkeypatch.setattr("os.path.getsize", racing_getsize)

    found = matching.iter_archive_files(str(root), ARCHIVE_EXTENSIONS)

    assert [path for path, _size in found] == [str(survivor)]
