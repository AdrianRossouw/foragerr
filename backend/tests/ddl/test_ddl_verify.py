"""Content verification before import (FRG-DDL-010)."""

from __future__ import annotations

import pytest

from foragerr.ddl.errors import DdlDownloadError
from foragerr.ddl.verify import SIZE_FLOOR_BYTES, verify_file
from ddl_support import make_cbz, make_pdf, make_zip_without_image


def _write(tmp_path, name: str, body: bytes):
    path = tmp_path / name
    path.write_bytes(body)
    return path


@pytest.mark.req("FRG-DDL-010")
def test_valid_cbz_opens_as_zip_with_an_image(tmp_path):
    path = _write(tmp_path, "ok.partial", make_cbz())
    verified = verify_file(path)
    assert verified.kind == "zip"
    assert verified.ext == ".cbz"


@pytest.mark.req("FRG-DDL-010")
def test_pdf_magic_accepted(tmp_path):
    path = _write(tmp_path, "ok.partial", make_pdf())
    assert verify_file(path).ext == ".pdf"


@pytest.mark.req("FRG-DDL-010")
def test_html_error_page_named_as_comic_is_rejected(tmp_path):
    body = b"<!doctype html><html><body>Not found</body></html>" + b" " * 20_000
    path = _write(tmp_path, "fake.partial", body)
    with pytest.raises(DdlDownloadError, match="magic bytes"):
        verify_file(path)


@pytest.mark.req("FRG-DDL-010")
def test_zip_without_image_entry_is_rejected(tmp_path):
    path = _write(tmp_path, "noimg.partial", make_zip_without_image())
    with pytest.raises(DdlDownloadError, match="no image"):
        verify_file(path)


@pytest.mark.req("FRG-DDL-010")
def test_file_below_size_floor_is_rejected(tmp_path):
    path = _write(tmp_path, "tiny.partial", b"PK\x03\x04tiny")
    assert len(b"PK\x03\x04tiny") < SIZE_FLOOR_BYTES
    with pytest.raises(DdlDownloadError, match="size floor"):
        verify_file(path)
