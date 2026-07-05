"""Hostile-archive corpus for the shared archive-safety utility
(FRG-SEC-003, FRG-PP-006).

The corpus is constructed in-test (small, deterministic) rather than committed
as opaque binaries: zip bomb (declared-oversize member), nested bomb, zip-slip
member name, absolute member name, symlink member, too-many-members,
total-too-large, encrypted/password-protected, corrupt, and bad-magic. Every
artifact must come back as a typed, bounded :class:`ArchiveReport` with
``ok=False`` and a ``reason_code`` — no extraction, no crash, no exhaustion.
"""

from __future__ import annotations

import stat
import zipfile

import pytest

from foragerr.security.archives import (
    DEFAULT_ARCHIVE_LIMITS,
    ArchiveLimits,
    inspect_archive,
)

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24


def _write_zip(path, entries, *, symlinks=None):
    """entries: list[(name, bytes)]; symlinks: set of names to mark as links."""
    symlinks = symlinks or set()
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries:
            if name in symlinks:
                info = zipfile.ZipInfo(name)
                info.create_system = 3  # unix
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                zf.writestr(info, data)
            else:
                zf.writestr(name, data)
    return path


def _write_encrypted_zip(path, name="secret.jpg"):
    """A zip whose one member has the encryption general-purpose bit set,
    crafted by flipping the flag in the local + central headers (stdlib zipfile
    cannot create encrypted archives)."""
    _write_zip(path, [(name, _PNG)])
    data = bytearray(path.read_bytes())
    data[data.find(b"PK\x03\x04") + 6] |= 0x01  # local file header flag
    data[data.find(b"PK\x01\x02") + 8] |= 0x01  # central directory flag
    path.write_bytes(bytes(data))
    return path


# --- happy paths -------------------------------------------------------------


@pytest.mark.req("FRG-PP-006")
def test_valid_cbz_with_image_is_accepted(tmp_path):
    cbz = _write_zip(tmp_path / "ok.cbz", [("page01.jpg", _PNG), ("page02.png", _PNG)])
    report = inspect_archive(cbz)
    assert report.ok
    assert report.kind == "zip"
    assert report.image_count == 2


@pytest.mark.req("FRG-PP-006")
def test_cbz_without_image_is_rejected(tmp_path):
    cbz = _write_zip(tmp_path / "noimg.cbz", [("readme.txt", b"hello world")])
    report = inspect_archive(cbz)
    assert not report.ok
    assert report.reason_code == "no_image_entries"


@pytest.mark.req("FRG-PP-006")
def test_cbr_passes_on_rar_magic_only_in_m1(tmp_path):
    cbr = tmp_path / "book.cbr"
    cbr.write_bytes(b"Rar!\x1a\x07\x00" + b"\x00" * 64)
    report = inspect_archive(cbr)
    assert report.ok
    assert report.kind == "rar"
    assert report.note  # documents the magic-only / unrar-absent residual


@pytest.mark.req("FRG-SEC-003")
def test_cb7_passes_on_magic_only_in_m1(tmp_path):
    cb7 = tmp_path / "book.cb7"
    cb7.write_bytes(b"7z\xbc\xaf\x27\x1c" + b"\x00" * 64)
    report = inspect_archive(cb7)
    assert report.ok
    assert report.kind == "7z"


# --- hostile corpus: each artifact is a typed, bounded rejection -------------


@pytest.mark.req("FRG-SEC-003")
@pytest.mark.req("FRG-PP-006")
def test_zip_slip_relative_member_rejected(tmp_path):
    z = _write_zip(tmp_path / "slip.cbz", [("../evil.jpg", _PNG), ("page.jpg", _PNG)])
    report = inspect_archive(z)
    assert not report.ok
    assert report.reason_code == "unsafe_member_path"
    assert report.offending_member == "../evil.jpg"


@pytest.mark.req("FRG-SEC-003")
def test_absolute_member_rejected(tmp_path):
    z = _write_zip(tmp_path / "abs.cbz", [("/etc/passwd", _PNG), ("page.jpg", _PNG)])
    report = inspect_archive(z)
    assert not report.ok
    assert report.reason_code == "unsafe_member_path"


@pytest.mark.req("FRG-SEC-003")
def test_symlink_member_rejected(tmp_path):
    z = _write_zip(
        tmp_path / "link.cbz",
        [("link", b"/etc/passwd"), ("page.jpg", _PNG)],
        symlinks={"link"},
    )
    report = inspect_archive(z)
    assert not report.ok
    assert report.reason_code == "symlink_member"


@pytest.mark.req("FRG-SEC-003")
def test_oversized_member_rejected(tmp_path):
    z = _write_zip(tmp_path / "big.cbz", [("page.jpg", b"x" * 4096)])
    limits = ArchiveLimits(max_member_bytes=1024)
    report = inspect_archive(z, limits)
    assert not report.ok
    assert report.reason_code == "member_too_large"


@pytest.mark.req("FRG-SEC-003")
def test_total_size_bomb_rejected(tmp_path):
    z = _write_zip(
        tmp_path / "bomb.cbz",
        [("a.jpg", b"x" * 2048), ("b.jpg", b"y" * 2048)],
    )
    limits = ArchiveLimits(max_member_bytes=4096, max_total_bytes=3000)
    report = inspect_archive(z, limits)
    assert not report.ok
    assert report.reason_code == "archive_too_large"


@pytest.mark.req("FRG-SEC-003")
def test_too_many_members_rejected(tmp_path):
    z = _write_zip(
        tmp_path / "many.cbz",
        [(f"page{i:03d}.jpg", _PNG) for i in range(3)],
    )
    report = inspect_archive(z, ArchiveLimits(max_members=2))
    assert not report.ok
    assert report.reason_code == "too_many_members"


@pytest.mark.req("FRG-SEC-003")
def test_nested_archive_member_rejected(tmp_path):
    z = _write_zip(tmp_path / "nested.cbz", [("inner.zip", _PNG), ("page.jpg", _PNG)])
    report = inspect_archive(z)
    assert not report.ok
    assert report.reason_code == "nested_archive"


@pytest.mark.req("FRG-SEC-003")
@pytest.mark.req("FRG-PP-006")
def test_password_protected_archive_rejected(tmp_path):
    z = _write_encrypted_zip(tmp_path / "enc.cbz")
    report = inspect_archive(z)
    assert not report.ok
    assert report.reason_code == "encrypted"


@pytest.mark.req("FRG-PP-006")
def test_corrupt_zip_rejected(tmp_path):
    z = tmp_path / "corrupt.cbz"
    z.write_bytes(b"PK\x03\x04" + b"garbage-not-a-real-zip")
    report = inspect_archive(z)
    assert not report.ok
    assert report.reason_code == "corrupt_zip"


@pytest.mark.req("FRG-PP-006")
def test_html_error_page_named_as_comic_rejected(tmp_path):
    z = tmp_path / "fake.cbz"
    z.write_bytes(b"<html><body>404 Not Found</body></html>")
    report = inspect_archive(z)
    assert not report.ok
    assert report.reason_code == "bad_magic"


@pytest.mark.req("FRG-SEC-003")
def test_whole_hostile_corpus_returns_typed_rejections_without_raising(tmp_path):
    builders = [
        lambda p: _write_zip(p, [("../evil.jpg", _PNG)]),
        lambda p: _write_zip(p, [("/abs.jpg", _PNG)]),
        lambda p: _write_zip(p, [("l", b"/etc"), ("p.jpg", _PNG)], symlinks={"l"}),
        lambda p: _write_zip(p, [("inner.cbz", _PNG), ("p.jpg", _PNG)]),
        lambda p: _write_encrypted_zip(p),
        lambda p: (p.write_bytes(b"PK\x03\x04garbage"), p)[1],
        lambda p: (p.write_bytes(b"<html>nope</html>"), p)[1],
    ]
    for i, build in enumerate(builders):
        path = build(tmp_path / f"corpus{i}.cbz")
        report = inspect_archive(path)  # must never raise
        assert not report.ok
        assert report.reason_code  # a machine-readable, typed reason
        assert report.reason  # a user-visible message


@pytest.mark.req("FRG-SEC-003")
def test_default_limits_accept_a_realistic_comic(tmp_path):
    entries = [(f"page{i:03d}.jpg", _PNG * 100) for i in range(30)]
    cbz = _write_zip(tmp_path / "real.cbz", entries)
    report = inspect_archive(cbz, DEFAULT_ARCHIVE_LIMITS)
    assert report.ok
    assert report.image_count == 30
