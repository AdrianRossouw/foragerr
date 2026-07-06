"""Safe file operations (FRG-PP-007) and folder lifecycle (FRG-PP-010)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from foragerr.importer import fileops
from foragerr.importer.fileops import (
    NotEnoughSpaceError,
    TransferError,
    TransferMode,
    cleanup_empty_dirs,
    place_file,
    quarantine_file,
)


@pytest.mark.req("FRG-PP-007")
def test_same_device_move_is_atomic_rename(tmp_path: Path):
    src = tmp_path / "in" / "a.cbz"
    src.parent.mkdir()
    src.write_bytes(b"comic-bytes")
    dst = tmp_path / "lib" / "Batman 001.cbz"
    place_file(src, dst, mode=TransferMode.MOVE, margin_bytes=0)
    assert dst.read_bytes() == b"comic-bytes"
    assert not src.exists()  # source removed after placement


@pytest.mark.req("FRG-PP-007")
def test_cross_device_copy_verify_delete(tmp_path: Path, monkeypatch):
    """When rename raises EXDEV, fall back to copy+verify+delete."""
    src = tmp_path / "a.cbz"
    src.write_bytes(b"x" * 4096)
    dst = tmp_path / "lib" / "Batman 001.cbz"

    real_replace = os.replace
    calls = {"n": 0}

    def fake_replace(a, b):
        # Fail only the first replace (the direct MOVE), let the temp promotion
        # inside copy-verify-delete succeed.
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError(18, "Invalid cross-device link")  # EXDEV
        return real_replace(a, b)

    monkeypatch.setattr(os, "replace", fake_replace)
    place_file(src, dst, mode=TransferMode.MOVE, margin_bytes=0)
    assert dst.read_bytes() == b"x" * 4096
    assert not src.exists()
    # No temp partial left behind in the destination directory.
    assert [p.name for p in dst.parent.iterdir()] == ["Batman 001.cbz"]


@pytest.mark.req("FRG-PP-007")
def test_free_space_margin_aborts_before_copy(tmp_path: Path, monkeypatch):
    src = tmp_path / "a.cbz"
    src.write_bytes(b"y" * 1000)
    dst = tmp_path / "lib" / "a.cbz"
    monkeypatch.setattr(fileops, "free_bytes", lambda _p: 500)  # less than needed
    with pytest.raises(NotEnoughSpaceError):
        place_file(src, dst, mode=TransferMode.MOVE, margin_bytes=100)
    assert src.exists()  # source intact
    assert not dst.exists()  # nothing written


@pytest.mark.req("FRG-PP-007")
def test_interrupted_transfer_leaves_no_partial_and_keeps_source(
    tmp_path: Path, monkeypatch
):
    """A copy that fails mid-flight leaves no file at the final path; source stays."""
    src = tmp_path / "a.cbz"
    src.write_bytes(b"z" * 8192)
    dst = tmp_path / "lib" / "a.cbz"

    def boom(*_a, **_k):
        raise OSError("disk exploded mid-copy")

    monkeypatch.setattr(fileops.shutil, "copyfileobj", boom)
    with pytest.raises(OSError):
        place_file(src, dst, mode=TransferMode.COPY, margin_bytes=0)
    assert src.read_bytes() == b"z" * 8192  # source retained
    assert not dst.exists()  # no partial at the final path
    assert not any(p.name.startswith(".foragerr-import-") for p in dst.parent.iterdir())


@pytest.mark.req("FRG-PP-007")
def test_size_mismatch_is_a_transfer_error(tmp_path: Path, monkeypatch):
    src = tmp_path / "a.cbz"
    src.write_bytes(b"z" * 100)
    dst = tmp_path / "lib" / "a.cbz"

    def short_copy(src_h, dst_h, length=0):
        dst_h.write(b"z" * 50)  # writes fewer bytes than the source

    monkeypatch.setattr(fileops.shutil, "copyfileobj", short_copy)
    with pytest.raises(TransferError):
        place_file(src, dst, mode=TransferMode.COPY, margin_bytes=0)
    assert src.exists() and not dst.exists()


@pytest.mark.req("FRG-PP-010")
def test_cleanup_removes_emptied_dirs_up_to_root(tmp_path: Path):
    root = tmp_path / "staging"
    deep = root / "release" / "sub"
    deep.mkdir(parents=True)
    (deep / ".DS_Store").write_bytes(b"junk")  # junk does not keep the dir alive
    removed = cleanup_empty_dirs(deep, root)
    assert str(deep) in removed
    assert str(root / "release") in removed
    assert root.exists()  # the stop root is never removed


@pytest.mark.req("FRG-PP-010")
def test_cleanup_keeps_dir_with_a_non_junk_sibling(tmp_path: Path):
    root = tmp_path / "staging"
    rel = root / "release"
    rel.mkdir(parents=True)
    (rel / "other.cbz").write_bytes(b"real")
    removed = cleanup_empty_dirs(rel, root)
    assert removed == []
    assert rel.exists()


@pytest.mark.req("FRG-PP-010")
def test_quarantine_moves_never_deletes(tmp_path: Path):
    src = tmp_path / "lib" / "old.cbz"
    src.parent.mkdir()
    src.write_bytes(b"superseded")
    config = tmp_path / "config"
    dest = quarantine_file(src, config, now=None)
    assert dest.exists() and dest.read_bytes() == b"superseded"
    assert not src.exists()
    assert "quarantine" in str(dest)


@pytest.mark.req("FRG-PP-010")
def test_quarantine_disambiguates_name_collisions(tmp_path: Path):
    config = tmp_path / "config"
    import datetime as dt

    now = dt.datetime(2026, 7, 5)
    first = tmp_path / "a.cbz"
    first.write_bytes(b"one")
    d1 = quarantine_file(first, config, now=now)
    second = tmp_path / "a.cbz"
    second.write_bytes(b"two")
    d2 = quarantine_file(second, config, now=now)
    assert d1 != d2
    assert d1.read_bytes() == b"one" and d2.read_bytes() == b"two"
