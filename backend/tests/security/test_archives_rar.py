"""RAR-backend mechanics for the shared archive-opener seam (FRG-OPDS-016).

The RAR half of ``list_image_members`` / ``read_image_member`` / ``inspect_archive``
is exercised against small, permissively-licensed RAR fixtures vendored from the
``rarfile`` project (``tests/fixtures/rar/`` — RAR creation is impossible in CI, see
that dir's README). Those fixtures carry only *text* members, so they prove the
backend mechanics — enumeration, natural-order + image filtering, single-member
streaming reads, the shared resource-limit ceilings, symlink/encrypted/absent-
backend degradation, and content-based routing of misnamed archives — while the
image-render half of the page-stream matrix is covered by the ZIP-renamed-``.cbr``
router test and an owner-fixture stub (see ``tests/test_opds_stream_cbr.py``).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from foragerr.security.archives import (
    ArchiveLimits,
    ArchiveMemberError,
    inspect_archive,
    list_image_members,
    read_image_member,
)

_FIXTURES = Path(__file__).parent.parent / "fixtures" / "rar"
_SUBDIRS = ["rar3-subdirs.rar", "rar5-subdirs.rar"]  # RAR4 + RAR5 mechanics


def _fixture(name: str) -> Path:
    p = _FIXTURES / name
    assert p.exists(), f"missing vendored fixture {p}"
    return p


# --- listing / safe_to_extract ------------------------------------------------


@pytest.mark.req("FRG-OPDS-016")
@pytest.mark.parametrize("name", _SUBDIRS)
def test_rar_inspect_lists_members_and_is_safe_to_extract(name):
    """A real RAR (RAR4 and RAR5) enumerates through ``rarfile`` and is honestly
    ``safe_to_extract`` — the same signal the ZIP path sets — so the shared page
    reader will serve it."""
    report = inspect_archive(str(_fixture(name)))
    assert report.ok and report.kind == "rar"
    assert report.listed is True
    assert report.safe_to_extract is True
    assert report.member_count > 0


@pytest.mark.req("FRG-OPDS-016")
@pytest.mark.parametrize("name", _SUBDIRS)
def test_rar_list_image_members_empty_when_no_image_members(name):
    """A listable RAR with no image members returns ``[]`` (listable, no pages) —
    NOT ``None`` (not listable) — exactly the ZIP parity for a text-only archive.
    Proves RAR enumeration reaches the shared image filter."""
    assert list_image_members(_fixture(name)) == []


# --- single-member streaming reads (never full extraction) --------------------


@pytest.mark.req("FRG-OPDS-016")
@pytest.mark.parametrize("name", _SUBDIRS)
def test_rar_single_member_streaming_read_returns_bytes(name):
    """One member is read through ``rarfile`` (an ``unrar`` subprocess for that
    member only — never a whole-archive extraction)."""
    data = read_image_member(_fixture(name), "sub/dir1/file1.txt", max_bytes=1_000_000)
    assert data == b"file1\n"


@pytest.mark.req("FRG-OPDS-016")
@pytest.mark.parametrize("name", _SUBDIRS)
def test_rar_read_member_over_declared_cap_refused_before_read(name):
    """The declared member size is checked BEFORE the read — a member over the
    per-page byte cap is refused pre-decompression, mirroring the ZIP path."""
    with pytest.raises(ArchiveMemberError):
        # file1.txt declares 6 bytes; cap of 1 is under it → refused pre-read.
        read_image_member(_fixture(name), "sub/dir1/file1.txt", max_bytes=1)


@pytest.mark.req("FRG-OPDS-016")
def test_rar_read_absent_member_raises():
    with pytest.raises(ArchiveMemberError):
        read_image_member(_fixture("rar5-subdirs.rar"), "nope.jpg", max_bytes=1_000_000)


@pytest.mark.req("FRG-OPDS-016")
def test_rar_read_member_rejects_traversal_and_absolute_names():
    for evil in ("../escape.jpg", "/etc/passwd", "a/../../x.jpg"):
        with pytest.raises(ArchiveMemberError):
            read_image_member(_fixture("rar5-subdirs.rar"), evil, max_bytes=1_000_000)


# --- security parity: symlink + encrypted degrade like the ZIP non-listable ---


@pytest.mark.req("FRG-OPDS-016")
def test_rar_with_symlink_member_is_rejected_and_non_listable():
    """A RAR carrying a symlink member is rejected at inspect (parity with ZIP's
    ``symlink_member`` rejection) and lists as ``None`` — no streamable pages."""
    report = inspect_archive(str(_fixture("rar5-symlink-unix.rar")))
    assert not report.ok
    assert report.reason_code == "symlink_member"
    assert list_image_members(_fixture("rar5-symlink-unix.rar")) is None


@pytest.mark.req("FRG-OPDS-016")
def test_encrypted_rar_degrades_to_non_listable():
    """An encrypted (header-password) RAR degrades to the non-listable residual —
    ``listed=False``, ``list_image_members`` → ``None`` (no PSE, stream 404) — never
    prompting for a password or raising."""
    report = inspect_archive(str(_fixture("rar5-hpsw.rar")))
    assert report.ok  # passes the validity gate (magic-only)
    assert report.listed is False
    assert report.safe_to_extract is False
    assert report.note  # documents the encrypted / non-listable residual
    assert list_image_members(_fixture("rar5-hpsw.rar")) is None


# --- resource limits: same ceilings as ZIP (task 2.7) -------------------------
# A true declared-size RAR "bomb" cannot be authored here (no RAR writer exists in
# CI). The limit CODE is instead driven against the real vendored archive with
# TIGHT limits — the identical ``_inspect_rar`` ceiling checks a bomb would trip.


@pytest.mark.req("FRG-OPDS-016")
def test_rar_member_count_ceiling_enforced():
    report = inspect_archive(str(_fixture("rar5-subdirs.rar")), ArchiveLimits(max_members=2))
    assert not report.ok
    assert report.reason_code == "too_many_members"


@pytest.mark.req("FRG-OPDS-016")
def test_rar_per_member_size_ceiling_enforced():
    report = inspect_archive(
        str(_fixture("rar5-subdirs.rar")), ArchiveLimits(max_member_bytes=1)
    )
    assert not report.ok
    assert report.reason_code == "member_too_large"


@pytest.mark.req("FRG-OPDS-016")
def test_rar_total_size_ceiling_enforced():
    report = inspect_archive(
        str(_fixture("rar5-subdirs.rar")),
        ArchiveLimits(max_member_bytes=1_000, max_total_bytes=10),
    )
    assert not report.ok
    assert report.reason_code == "archive_too_large"


@pytest.mark.req("FRG-OPDS-016")
def test_rar_ceiling_over_limit_makes_it_non_listable():
    """An over-cap RAR is ``safe_to_extract=False`` → ``list_image_members`` None,
    so the whole limit framework short-circuits page streaming (single-member
    reads only, never a full extraction to disk)."""
    limits = ArchiveLimits(max_members=2)
    assert list_image_members(_fixture("rar5-subdirs.rar"), limits) is None


# --- backend absence: degrade, never error (task 2.6) -------------------------


@pytest.mark.req("FRG-OPDS-016")
def test_rar_backend_absent_degrades_everywhere(monkeypatch):
    """With ``rarfile`` unimportable, a real RAR degrades to the magic-only,
    non-listable residual across the whole seam: inspect passes on magic
    (``listed=False``), ``list_image_members`` → ``None`` (no PSE), and a page read
    raises a typed :class:`ArchiveMemberError` (bounded 5xx) — never a crash."""
    # ``sys.modules[name] = None`` makes ``import name`` raise ImportError — the
    # exact absent-backend condition the Docker image guards against.
    monkeypatch.setitem(sys.modules, "rarfile", None)

    report = inspect_archive(str(_fixture("rar5-subdirs.rar")))
    assert report.ok and report.kind == "rar"
    assert report.listed is False
    assert report.safe_to_extract is False
    assert report.note  # magic-only residual documented

    assert list_image_members(_fixture("rar5-subdirs.rar")) is None

    with pytest.raises(ArchiveMemberError):
        read_image_member(_fixture("rar5-subdirs.rar"), "sub/dir1/file1.txt", max_bytes=99)


# --- content-based routing of misnamed archives (task 2.5, RAR→.cbz) ----------


@pytest.mark.req("FRG-OPDS-016")
def test_rar_renamed_cbz_routes_by_content(tmp_path):
    """A RAR whose extension lies (``.cbz``) still routes to the RAR opener by
    magic — it lists (``[]`` here, not ``None``-via-BadZipFile) and a member reads
    correctly. Extension is a hint only; content decides the opener."""
    misnamed = tmp_path / "actually_a_rar.cbz"
    misnamed.write_bytes(_fixture("rar5-subdirs.rar").read_bytes())

    report = inspect_archive(str(misnamed))
    assert report.kind == "rar"  # not mis-parsed as a corrupt zip
    assert report.listed is True

    # Routed to the RAR opener, not the ZIP opener (a ZIP opener would BadZipFile
    # → None); a text-only RAR lists as [] (listable, no image pages).
    assert list_image_members(misnamed) == []
    assert (
        read_image_member(misnamed, "sub/dir1/file1.txt", max_bytes=1_000_000)
        == b"file1\n"
    )


# Keep the real ``rarfile`` module importable for the rest of the session after
# the monkeypatched-absence test (importlib re-imports on next access anyway; this
# is belt-and-braces so a fixture-file discovery import never sees ``None``).
def teardown_module(module):  # noqa: D401 - pytest hook
    if sys.modules.get("rarfile") is None:
        del sys.modules["rarfile"]
        importlib.import_module("rarfile")
