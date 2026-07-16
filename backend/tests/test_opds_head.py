"""OPDS HEAD parity (FRG-OPDS-017).

Reader apps and proxies preflight OPDS URLs with HEAD; the routes must answer
HEAD with the same status, auth challenge, and content headers as GET — with no
body, and without doing the expensive archive read/decode for the file/page
routes. Seeds a real CBZ with a genuine JPEG page so the page route's GET
returns a real 200 the HEAD is compared against.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from foragerr.app import create_app
from opds_support import opds_settings, seed, simple_series


@pytest.fixture
def settings(tmp_path: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    return opds_settings(cfg)


@pytest.fixture
def client(settings):
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def _cbz_with_image() -> bytes:
    buf = io.BytesIO()
    img = io.BytesIO()
    Image.new("RGB", (200, 300), (100, 40, 20)).save(img, "JPEG")
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("p1.jpg", img.getvalue())
    return buf.getvalue()


def _seed_image_library(client, tmp_path):
    """One series with a single real-image CBZ; returns the issue-file id."""
    spec = {
        "title": "Saga",
        "cv_volume_id": 1,
        "issues": [
            {
                "cv_issue_id": 1001,
                "number": "1",
                "files": [{"name": "Saga 001.cbz", "data": _cbz_with_image()}],
            }
        ],
    }
    data = client.portal.call(seed, client.app, tmp_path / "library", [spec])
    return data["series"][0]["issues"][0]["files"][0]["id"]


def _assert_head_mirrors_get(client, url: str) -> None:
    get = client.get(url)
    head = client.head(url)
    assert get.status_code == 200
    assert head.status_code == get.status_code
    # Content type (the header readers key off) matches the GET exactly.
    assert head.headers["content-type"] == get.headers["content-type"]
    # HEAD carries no body.
    assert head.content == b""


@pytest.mark.req("FRG-OPDS-017")
def test_head_mirrors_get_on_root_and_series_feeds(client, tmp_path):
    client.portal.call(seed, client.app, tmp_path / "library", [simple_series()])
    _assert_head_mirrors_get(client, "/opds")
    _assert_head_mirrors_get(client, "/opds/series")


@pytest.mark.req("FRG-OPDS-017")
def test_head_mirrors_get_on_acquisition_file(client, tmp_path):
    fid = _seed_image_library(client, tmp_path)
    get = client.get(f"/opds/file/{fid}")
    head = client.head(f"/opds/file/{fid}")
    assert get.status_code == 200 and head.status_code == 200
    assert head.headers["content-type"] == get.headers["content-type"]
    # Content-Length is answered from the file stat, not a body read.
    assert head.headers["content-length"] == get.headers["content-length"]
    assert head.content == b""


@pytest.mark.req("FRG-OPDS-017")
def test_head_mirrors_get_on_page_stream(client, tmp_path):
    fid = _seed_image_library(client, tmp_path)
    get = client.get(f"/opds/page/{fid}/0")
    head = client.head(f"/opds/page/{fid}/0")
    assert get.status_code == 200 and head.status_code == 200
    assert head.headers["content-type"] == get.headers["content-type"] == "image/jpeg"
    assert head.content == b""


@pytest.mark.req("FRG-OPDS-017")
def test_head_on_unknown_file_id_404s_like_get(client, tmp_path):
    client.portal.call(seed, client.app, tmp_path / "library", [simple_series()])
    assert client.get("/opds/file/999999").status_code == 404
    assert client.head("/opds/file/999999").status_code == 404


@pytest.mark.req("FRG-OPDS-017")
def test_unauthenticated_head_still_challenges_basic(client, tmp_path):
    client.portal.call(seed, client.app, tmp_path / "library", [simple_series()])
    # Drop the auto-attached API key so the request is credential-free.
    client.headers.pop("X-Api-Key", None)
    resp = client.head("/opds")
    assert resp.status_code == 401
    assert resp.headers["WWW-Authenticate"].lower().startswith("basic")
    # Same challenge a bare GET would receive.
    get = client.get("/opds")
    assert get.status_code == 401
    assert get.headers["WWW-Authenticate"] == resp.headers["WWW-Authenticate"]


def _cbz_without_images() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", b"no pages here" * 4000)
    return buf.getvalue()


@pytest.mark.req("FRG-OPDS-017")
def test_head_404s_out_of_range_page_like_get(client, tmp_path):
    """HEAD must run GET's existence checks (Codex gate finding): an
    out-of-range page 404s on both verbs, never 200-on-HEAD/404-on-GET."""
    fid = _seed_image_library(client, tmp_path)
    url = f"/opds/page/{fid}/99"
    assert client.get(url).status_code == 404
    assert client.head(url).status_code == 404


@pytest.mark.req("FRG-OPDS-017")
def test_head_404s_imageless_archive_like_get(client, tmp_path):
    """An archive with no image members 404s on page AND cover HEAD exactly
    as on GET (no false 'cover exists' preflight)."""
    spec = {
        "title": "Textless",
        "cv_volume_id": 2,
        "issues": [
            {
                "cv_issue_id": 2001,
                "number": "1",
                "files": [
                    {"name": "Textless 001.cbz", "data": _cbz_without_images()}
                ],
            }
        ],
    }
    data = client.portal.call(seed, client.app, tmp_path / "library", [spec])
    fid = data["series"][0]["issues"][0]["files"][0]["id"]
    for url in (f"/opds/page/{fid}/0", f"/opds/cover/{fid}"):
        assert client.get(url).status_code in (404, 502)
        assert client.head(url).status_code == client.get(url).status_code
