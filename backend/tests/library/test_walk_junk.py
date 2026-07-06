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
    """AppleDouble/@eaDir dirs, ``._`` forks, dotfiles, and unpack-temp folders
    are all skipped; an UPPERCASE extension is recognized. Zero-byte files are
    NOT walk-level junk: they enumerate so ``JunkFilterSpec`` blocks them
    visibly (FRG-PP-005), and a user folder that merely starts with
    ``_unpack``-without-the-trailing-underscore is a real library folder."""
    root = tmp_path / "library"
    real_lower = _touch(root / "Saga (2012)" / "Saga 001 (2012).cbz")
    real_upper = _touch(root / "Saga (2012)" / "Saga 002 (2012).CBZ")
    # Zero-byte "archive": enumerated (blocked later, visibly), never skipped.
    empty = _touch(root / "Saga (2012)" / "empty.cbz", b"")
    # A user folder, NOT an unpack-temp dir (no trailing underscore marker).
    extras = _touch(root / "_unpacked extras" / "Saga Annual (2013).cbz")

    # Junk files alongside the real archives.
    _touch(root / "Saga (2012)" / "._Saga 001 (2012).cbz")  # resource fork
    _touch(root / "Saga (2012)" / ".hidden.cbz")  # dotfile
    # Junk directories that must never be descended into.
    _touch(root / "@eaDir" / "thumb.cbz")
    _touch(root / ".AppleDouble" / "Saga 001 (2012).cbz")
    _touch(root / "_UNPACK_Saga.003" / "Saga 003 (2012).cbz")
    _touch(root / "Saga (2012)" / "_unpack_tmp" / "partial.cbz")

    found = matching.iter_archive_files(str(root), ARCHIVE_EXTENSIONS)

    assert sorted(path for path, _size in found) == sorted(
        [str(real_lower), str(real_upper), str(empty), str(extras)]
    )


@pytest.mark.req("FRG-IMP-022")
def test_junk_predicates_direct():
    assert matching.is_junk_dir("@eaDir")
    assert matching.is_junk_dir(".AppleDouble")
    assert matching.is_junk_dir("_UNPACK_Some.Release")  # SABnzbd unpack temp
    assert matching.is_junk_dir("_unpack_tmp")
    assert not matching.is_junk_dir("Saga (2012)")
    assert not matching.is_junk_dir("Undertow (2014)")  # no false _unpack prefix
    # The trailing underscore is part of the unpack-temp marker: a user's
    # folder is never pruned for merely starting with "_unpack".
    assert not matching.is_junk_dir("_unpacked extras")
    assert not matching.is_junk_dir("_unpackrat comics")

    assert matching.is_junk_file("._fork.cbz")
    assert matching.is_junk_file(".hidden.cbz")
    assert not matching.is_junk_file("Saga 001.cbz")


@pytest.mark.req("FRG-IMP-022")
@pytest.mark.req("FRG-PP-005")
def test_zero_byte_single_file_root_is_yielded_for_visible_blocking(tmp_path: Path):
    """A zero-byte file is not silently dropped by the walk: it enumerates (with
    its 0 size) so the decision engine's JunkFilterSpec blocks it VISIBLY in
    rescan reports / manual-import listings / download blocked reasons."""
    empty = _touch(tmp_path / "empty.cbz", b"")
    assert matching.iter_archive_files(str(empty), ARCHIVE_EXTENSIONS) == [
        (str(empty), 0)
    ]


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
