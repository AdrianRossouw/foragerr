"""Embedded ComicInfo.xml read (FRG-IMP-024, read half).

Unit coverage of :mod:`foragerr.metadata.comicinfo`: member selection, the
declared-size cap, parse-degradation on malformed/hostile input, and the
"vetted-member-list only, no extraction" contract. The reconciliation trust rules
(verified vs conflicting) are exercised at the pipeline level in
``tests/importer/test_manual_import.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from foragerr.metadata.comicinfo import (
    COMICINFO_MAX_BYTES,
    EmbeddedMetadata,
    read_embedded_metadata,
)
from foragerr.security.archives import inspect_archive

from importer._archives import comicinfo_xml, make_cbz, make_cbz_with_comicinfo


def _read(path: Path) -> EmbeddedMetadata | None:
    return read_embedded_metadata(str(path), inspect_archive(str(path)))


@pytest.mark.req("FRG-IMP-024")
def test_cv_issue_id_read_from_web_url(tmp_path: Path):
    cbz = tmp_path / "b.cbz"
    make_cbz_with_comicinfo(cbz, xml=comicinfo_xml(cv_issue_id=9001, web=True))
    meta = _read(cbz)
    assert meta is not None
    assert meta.comic_info_present is True
    assert meta.cv_issue_id == 9001
    assert meta.series == "Batman"
    assert meta.parse_error is None


@pytest.mark.req("FRG-IMP-024")
def test_cv_issue_id_read_from_notes_fallback(tmp_path: Path):
    cbz = tmp_path / "b.cbz"
    make_cbz_with_comicinfo(
        cbz, xml=comicinfo_xml(cv_issue_id=7777, web=False, notes=True)
    )
    meta = _read(cbz)
    assert meta is not None and meta.cv_issue_id == 7777


@pytest.mark.req("FRG-IMP-024")
def test_member_selection_is_case_insensitive_and_root_only(tmp_path: Path):
    upper = tmp_path / "u.cbz"
    make_cbz_with_comicinfo(
        upper, xml=comicinfo_xml(cv_issue_id=42), member_name="COMICINFO.XML"
    )
    assert (_read(upper) or EmbeddedMetadata()).cv_issue_id == 42

    nested = tmp_path / "n.cbz"
    make_cbz_with_comicinfo(
        nested, xml=comicinfo_xml(cv_issue_id=42), member_name="meta/ComicInfo.xml"
    )
    # A non-root member is not the metadata member — nothing embedded.
    assert _read(nested) is None


@pytest.mark.req("FRG-IMP-024")
def test_oversized_comicinfo_member_skipped_before_read(tmp_path: Path):
    cbz = tmp_path / "big.cbz"
    make_cbz_with_comicinfo(
        cbz, xml=comicinfo_xml(pad_bytes=COMICINFO_MAX_BYTES + 1024)
    )
    # Declared size is over the per-member cap → skipped before any read, no
    # unbounded load, no crash.
    assert _read(cbz) is None


@pytest.mark.req("FRG-IMP-024")
def test_malformed_comicinfo_degrades_with_parse_error(tmp_path: Path):
    cbz = tmp_path / "m.cbz"
    make_cbz_with_comicinfo(cbz, xml="<ComicInfo><Series>Batman")  # not well-formed
    meta = _read(cbz)
    assert meta is not None
    assert meta.comic_info_present is True
    assert meta.parse_error is not None
    assert meta.cv_issue_id is None


@pytest.mark.req("FRG-IMP-024")
def test_hostile_dtd_comicinfo_rejected_by_hardening(tmp_path: Path):
    hostile = (
        '<?xml version="1.0"?>\n'
        "<!DOCTYPE ComicInfo [<!ENTITY x SYSTEM 'file:///etc/passwd'>]>\n"
        "<ComicInfo><Series>&x;</Series></ComicInfo>"
    )
    cbz = tmp_path / "x.cbz"
    make_cbz_with_comicinfo(cbz, xml=hostile)
    meta = _read(cbz)
    # The single hardened parser rejects the DTD/entity payload → parse-degraded,
    # never resolves the external entity, never raises.
    assert meta is not None and meta.parse_error is not None
    assert meta.cv_issue_id is None


@pytest.mark.req("FRG-IMP-024")
def test_absent_comicinfo_yields_none(tmp_path: Path):
    cbz = tmp_path / "plain.cbz"
    make_cbz(cbz)
    assert _read(cbz) is None


@pytest.mark.req("FRG-IMP-024")
def test_unlisted_and_failed_archives_yield_none(tmp_path: Path):
    # Magic-only cbr (no vetted member list) → no embedded read.
    cbr = tmp_path / "m.cbr"
    cbr.write_bytes(b"Rar!\x1a\x07\x00" + b"\x00" * 64)
    report = inspect_archive(str(cbr))
    assert report.listed is False
    assert read_embedded_metadata(str(cbr), report) is None

    # A failed/corrupt archive report → no read attempted.
    corrupt = tmp_path / "bad.cbz"
    corrupt.write_bytes(b"<html>not a zip</html>")
    bad_report = inspect_archive(str(corrupt))
    assert bad_report.ok is False
    assert read_embedded_metadata(str(corrupt), bad_report) is None


@pytest.mark.req("FRG-IMP-024")
def test_unsupported_compression_method_degrades_to_none(tmp_path, monkeypatch):
    """A member whose declared compression is unsupported makes ``ZipFile.read``
    raise ``NotImplementedError`` — it must degrade to no evidence, honouring the
    'never raises' contract, not escape into the pipeline (regression)."""
    import zipfile as _zip

    cbz = tmp_path / "u.cbz"
    make_cbz_with_comicinfo(cbz, xml=comicinfo_xml(cv_issue_id=9001))
    report = inspect_archive(str(cbz))  # inspected before the read is patched

    def _boom(self, name):
        raise NotImplementedError("compression type 99 (unsupported)")

    monkeypatch.setattr(_zip.ZipFile, "read", _boom)
    assert read_embedded_metadata(str(cbz), report) is None


@pytest.mark.req("FRG-IMP-024")
def test_corrupt_deflate_stream_degrades_to_none(tmp_path, monkeypatch):
    """A corrupt deflate stream makes ``ZipFile.read`` raise ``zlib.error`` —
    also degraded to no evidence rather than escaping (regression)."""
    import zipfile as _zip
    import zlib

    cbz = tmp_path / "z.cbz"
    make_cbz_with_comicinfo(cbz, xml=comicinfo_xml(cv_issue_id=9001))
    report = inspect_archive(str(cbz))

    def _boom(self, name):
        raise zlib.error("Error -3 while decompressing data: invalid distance")

    monkeypatch.setattr(_zip.ZipFile, "read", _boom)
    assert read_embedded_metadata(str(cbz), report) is None


@pytest.mark.req("FRG-IMP-024")
def test_read_extracts_nothing_to_disk(tmp_path: Path):
    cbz = tmp_path / "b.cbz"
    make_cbz_with_comicinfo(cbz, xml=comicinfo_xml(cv_issue_id=9001))
    before = sorted(p.name for p in tmp_path.iterdir())
    meta = _read(cbz)
    after = sorted(p.name for p in tmp_path.iterdir())
    assert meta is not None and meta.cv_issue_id == 9001
    # In-memory read only — nothing extracted alongside the archive.
    assert before == after == ["b.cbz"]
