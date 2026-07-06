"""OPDS download-route tests: id-only resolution, containment, byte-identical
whole-file downloads with the correct comic MIME types, and the download-side
security posture (FRG-OPDS-003, FRG-OPDS-005).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from foragerr.library import repo
from foragerr.app import create_app
from opds_support import opds_settings, seed

CBZ = "application/vnd.comicbook+zip"
CBR = "application/vnd.comicbook-rar"


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


def _mixed_library_spec() -> dict:
    return {
        "title": "Mixed",
        "cv_volume_id": 7,
        "issues": [
            {
                "cv_issue_id": 71,
                "number": "1",
                "cover_date": dt.date(2012, 1, 1),
                "files": [{"name": "Mixed 001.cbz", "data": b"CBZ\x00\x01bytes-A" * 8}],
            },
            {
                "cv_issue_id": 72,
                "number": "2",
                "files": [{"name": "Mixed 002.cbr", "data": b"CBR\xff\xfebytes-B" * 8}],
            },
            {
                "cv_issue_id": 73,
                "number": "3",
                "files": [{"name": "Mixed 003.pdf", "data": b"%PDF-1.4 bytes-C" * 8}],
            },
        ],
    }


def _seed(client, tmp_path, spec):
    return client.portal.call(seed, client.app, tmp_path / "library", spec)


# --- FRG-OPDS-005: byte-identical downloads with exact MIME ------------------


@pytest.mark.req("FRG-OPDS-005")
def test_cbz_download_is_byte_identical_with_zip_comic_mime(client, tmp_path):
    data = _seed(client, tmp_path, [_mixed_library_spec()])
    f = data["series"][0]["issues"][0]["files"][0]

    # The feed link advertises the same type the download serves.
    from xml.etree import ElementTree as ET

    feed = ET.fromstring(client.get(f"/opds/series/{data['series'][0]['id']}").text)
    acq = [
        link.get("type")
        for link in feed.findall(".//{http://www.w3.org/2005/Atom}link")
        if link.get("rel") == "http://opds-spec.org/acquisition"
        and link.get("href") == f"/opds/file/{f['id']}"
    ]
    assert acq == [CBZ]

    resp = client.get(f"/opds/file/{f['id']}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == CBZ
    assert resp.content == f["data"]  # byte-identical
    # Starlette RFC 5987-encodes a filename containing a space.
    from urllib.parse import quote

    disposition = resp.headers["content-disposition"]
    assert "attachment" in disposition
    assert f["name"] in disposition or quote(f["name"]) in disposition


@pytest.mark.req("FRG-OPDS-005")
def test_cbr_download_is_byte_identical_with_rar_comic_mime(client, tmp_path):
    data = _seed(client, tmp_path, [_mixed_library_spec()])
    f = data["series"][0]["issues"][1]["files"][0]
    resp = client.get(f"/opds/file/{f['id']}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == CBR
    assert resp.content == f["data"]


@pytest.mark.req("FRG-OPDS-005")
def test_no_format_is_served_as_octet_stream(client, tmp_path):
    data = _seed(client, tmp_path, [_mixed_library_spec()])
    expected = {".cbz": CBZ, ".cbr": CBR, ".pdf": "application/pdf"}
    for issue in data["series"][0]["issues"]:
        f = issue["files"][0]
        resp = client.get(f"/opds/file/{f['id']}")
        assert resp.status_code == 200
        ct = resp.headers["content-type"]
        assert ct != "application/octet-stream"
        assert ct == expected[Path(f["name"]).suffix]


# --- FRG-OPDS-003: id-only resolution + containment -------------------------


@pytest.mark.req("FRG-OPDS-003")
def test_download_takes_only_an_integer_id(client, tmp_path):
    data = _seed(client, tmp_path, [_mixed_library_spec()])
    f = data["series"][0]["issues"][0]["files"][0]
    # A valid id serves; a non-integer id is a 422 (type validation), never a
    # path the server would try to open.
    assert client.get(f"/opds/file/{f['id']}").status_code == 200
    # A non-integer id is rejected at the type boundary (the app maps request
    # validation to 400) — never treated as a path.
    assert client.get("/opds/file/not-an-int").status_code == 400


@pytest.mark.req("FRG-OPDS-003")
def test_unknown_id_returns_404_no_bytes(client, tmp_path):
    _seed(client, tmp_path, [_mixed_library_spec()])
    resp = client.get("/opds/file/999999")
    assert resp.status_code == 404
    assert resp.content != b"%PDF"  # nothing served


@pytest.mark.req("FRG-OPDS-003")
def test_foreign_path_outside_root_returns_404(client, tmp_path):
    """An issue-file row whose stored path escaped every managed root (the
    shape a compromised/legacy row would take) is served as 404 — the
    containment check refuses it and no out-of-library bytes leave."""
    data = _seed(client, tmp_path, [_mixed_library_spec()])
    issue_id = data["series"][0]["issues"][0]["id"]

    # Point a fresh issue-file at a real file OUTSIDE any root folder.
    outside = tmp_path / "outside" / "secret.cbz"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_bytes(b"do-not-serve")

    async def _add_rogue(app):
        async with app.state.db.write_session() as session:
            row = await repo.add_issue_file(
                session, issue_id=issue_id, path=str(outside), size=12
            )
            return row.id

    rogue_id = client.portal.call(_add_rogue, client.app)
    resp = client.get(f"/opds/file/{rogue_id}")
    assert resp.status_code == 404
    assert b"do-not-serve" not in resp.content


@pytest.mark.req("FRG-OPDS-003")
def test_deliverfile_traversal_is_unrepresentable(client, tmp_path):
    """The Mylar ?cmd=deliverFile&file=/etc/passwd class cannot be expressed:
    there is no OPDS route/param that accepts a path."""
    _seed(client, tmp_path, [_mixed_library_spec()])
    # Encoded traversal in the id slot is not an int -> 400/404, never a lookup.
    assert client.get("/opds/file/..%2f..%2f..%2fetc%2fpasswd").status_code in (400, 404, 422)
    # A path smuggled as a query param is simply ignored by the id-only route.
    resp = client.get("/opds/file/1", params={"file": "/etc/passwd"})
    # id 1 may or may not exist here, but the ?file= param has no effect.
    assert resp.status_code in (200, 404)
    assert b"root:" not in resp.content
