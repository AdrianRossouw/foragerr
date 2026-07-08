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
    ArchiveMemberError,
    inspect_archive,
    list_image_members,
    natural_sort_key,
    read_image_member,
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


@pytest.mark.req("FRG-SEC-003")
def test_safe_to_extract_distinguishes_vetted_from_magic_only(tmp_path):
    # A fully-listed + vetted zip is honestly safe to extract; a magic-only
    # container (7z, or magic-only cbr) is ok=True but NOT safe_to_extract, so a
    # future extractor can never mistake an unlistable archive for "members
    # vetted". listed/safe_to_extract are distinct from ok.
    cbz = _write_zip(tmp_path / "ok.cbz", [("page01.jpg", _PNG)])
    zip_report = inspect_archive(cbz)
    assert zip_report.ok and zip_report.listed and zip_report.safe_to_extract

    cb7 = tmp_path / "book.cb7"
    cb7.write_bytes(b"7z\xbc\xaf\x27\x1c" + b"\x00" * 64)
    magic_report = inspect_archive(cb7)
    assert magic_report.ok  # passes the M1 validity gate
    assert not magic_report.listed  # but no member was enumerated
    assert not magic_report.safe_to_extract  # so extraction must not trust it

    # A rejected archive is likewise never safe to extract.
    bad = _write_zip(tmp_path / "noimg.cbz", [("readme.txt", b"hello")])
    bad_report = inspect_archive(bad)
    assert not bad_report.ok and not bad_report.safe_to_extract


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


# --- OPDS page streaming: ordered image-member listing (FRG-OPDS-010) ---------


@pytest.mark.req("FRG-OPDS-010")
def test_list_image_members_natural_order_ignores_dir_and_comicinfo(tmp_path):
    # Members deliberately shuffled and unpadded so a lexical sort would give
    # 1, 10, 2; natural order must give 1, 2, 10. A directory entry and a
    # ComicInfo.xml member must not appear (nor shift numbering).
    cbz = _write_zip(
        tmp_path / "pages.cbz",
        [
            ("10.jpg", _PNG),
            ("2.jpg", _PNG),
            ("1.jpg", _PNG),
            ("sub/", b""),
            ("ComicInfo.xml", b"<ComicInfo/>"),
        ],
    )
    members = list_image_members(cbz)
    assert members == ["1.jpg", "2.jpg", "10.jpg"]
    assert len(members) == 3  # count == len(list), ComicInfo/dir excluded


@pytest.mark.req("FRG-OPDS-010")
def test_list_image_members_excludes_non_image_members(tmp_path):
    cbz = _write_zip(
        tmp_path / "mixed.cbz",
        [("01.jpg", _PNG), ("notes.txt", b"x"), ("02.png", _PNG)],
    )
    members = list_image_members(cbz)
    assert members == ["01.jpg", "02.png"]  # non-image dropped


@pytest.mark.req("FRG-OPDS-010")
def test_list_image_members_none_when_archive_has_symlink_member(tmp_path):
    # A symlink member makes the whole archive unlistable (inspect_archive
    # rejects it, safe_to_extract=False), so there are no streamable pages. The
    # in-listing symlink filter is defense-in-depth behind that gate.
    cbz = _write_zip(
        tmp_path / "link.cbz",
        [("01.jpg", _PNG), ("evil.jpg", b"/etc/passwd")],
        symlinks={"evil.jpg"},
    )
    assert list_image_members(cbz) is None


@pytest.mark.req("FRG-OPDS-010")
def test_list_image_members_zero_images_is_empty_not_none(tmp_path):
    # A listable zip with no image members: [] (listable, no pages), NOT None.
    cbz = _write_zip(tmp_path / "textonly.cbz", [("readme.txt", b"hello")])
    assert list_image_members(cbz) == []


@pytest.mark.req("FRG-OPDS-010")
def test_list_image_members_unlistable_cbr_is_none(tmp_path):
    # A RAR-magic file with no rarfile/unVERTED members: safe_to_extract=False,
    # so no page listing (design §5 CBR degradation).
    cbr = tmp_path / "book.cbr"
    cbr.write_bytes(b"Rar!\x1a\x07\x00" + b"\x00" * 64)
    assert list_image_members(cbr) is None


@pytest.mark.req("FRG-OPDS-010")
def test_list_image_members_corrupt_archive_is_none(tmp_path):
    bad = tmp_path / "bad.cbz"
    bad.write_bytes(b"<html>404</html>")
    assert list_image_members(bad) is None


@pytest.mark.req("FRG-OPDS-010")
def test_natural_sort_key_is_padding_insensitive():
    names = ["10.jpg", "0002.jpg", "1.jpg", "002.jpg"]
    ordered = sorted(names, key=natural_sort_key)
    assert ordered == ["1.jpg", "0002.jpg", "002.jpg", "10.jpg"]


# --- OPDS page streaming: safe single-member reader (FRG-OPDS-012) ------------


@pytest.mark.req("FRG-OPDS-012")
def test_read_image_member_returns_bytes_within_cap(tmp_path):
    cbz = _write_zip(tmp_path / "ok.cbz", [("01.jpg", _PNG)])
    data = read_image_member(cbz, "01.jpg", max_bytes=1_000_000)
    assert data == _PNG


@pytest.mark.req("FRG-OPDS-012")
def test_read_image_member_over_cap_refused_before_read(tmp_path):
    payload = b"\xff" * 5_000
    cbz = _write_zip(tmp_path / "big.cbz", [("01.jpg", payload)])
    with pytest.raises(ArchiveMemberError):
        # declared file_size (5000) > cap (100) => refused pre-decompression
        read_image_member(cbz, "01.jpg", max_bytes=100)


@pytest.mark.req("FRG-OPDS-012")
def test_read_image_member_rejects_traversal_and_absolute_names(tmp_path):
    cbz = _write_zip(tmp_path / "ok.cbz", [("01.jpg", _PNG)])
    for evil in ("../escape.jpg", "/etc/passwd", "a/../../x.jpg"):
        with pytest.raises(ArchiveMemberError):
            read_image_member(cbz, evil, max_bytes=1_000_000)


@pytest.mark.req("FRG-OPDS-012")
def test_read_image_member_rejects_symlink_member(tmp_path):
    cbz = _write_zip(
        tmp_path / "link.cbz",
        [("page.jpg", _PNG), ("evil.jpg", b"/etc/passwd")],
        symlinks={"evil.jpg"},
    )
    with pytest.raises(ArchiveMemberError):
        read_image_member(cbz, "evil.jpg", max_bytes=1_000_000)


@pytest.mark.req("FRG-OPDS-012")
def test_read_image_member_absent_member_raises(tmp_path):
    cbz = _write_zip(tmp_path / "ok.cbz", [("01.jpg", _PNG)])
    with pytest.raises(ArchiveMemberError):
        read_image_member(cbz, "nope.jpg", max_bytes=1_000_000)
