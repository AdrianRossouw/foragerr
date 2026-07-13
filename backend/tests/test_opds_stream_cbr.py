"""OPDS-PSE page-stream parity for CBR / misnamed archives (FRG-OPDS-016).

Extends the CBZ page-stream suite (``test_opds_stream.py``) to the RAR-backed
class. The image-render matrix (PSE link, ``pse:count``, in/out-of-range, width
cap, lazy NULL-count heal) is driven through a ZIP archive on a ``.cbr`` path —
the content-detection seam routes it to the ZIP opener, so it exercises the full
list → read → decode → downscale path against a ``.cbr`` file with real image
bytes. A true image-bearing RAR render is an owner-fixture stub (RAR creation is
impossible in CI). Backend-degradation is driven through an encrypted RAR on a
``.cbr`` path (non-listable → no PSE, stream 404).
"""

from __future__ import annotations

import datetime as dt
import io
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from foragerr.app import create_app
from foragerr.library.models import IssueFileRow
from opds_support import opds_settings, seed

ATOM = "{http://www.w3.org/2005/Atom}"
PSE = "{http://vaemendis.net/opds-pse/ns}"
REL_PSE_STREAM = "http://vaemendis.net/opds-pse/stream"

_RAR_FIXTURES = Path(__file__).parent / "fixtures" / "rar"


# --- fixtures & builders -----------------------------------------------------


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


def _png(w: int, h: int, color=(30, 90, 160)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


def _zip_bytes(members: list[tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members:
            zf.writestr(name, data)
    return buf.getvalue()


def _spec(title: str, cv: int, files: list[dict]) -> dict:
    return {
        "title": title,
        "cv_volume_id": cv,
        "issues": [
            {
                "cv_issue_id": cv * 1000 + i + 1,
                "number": str(i + 1),
                "cover_date": dt.date(2012, 1, 1),
                "files": [f],
            }
            for i, f in enumerate(files)
        ],
    }


def _seed(client, tmp_path, spec):
    return client.portal.call(seed, client.app, tmp_path / "library", spec)


def _set_page_count(client, file_id: int, count: int | None) -> None:
    async def _do(app):
        async with app.state.db.write_session() as session:
            row = await session.get(IssueFileRow, file_id)
            row.page_count = count

    client.portal.call(_do, client.app)


def _read_page_count(client, file_id: int) -> int | None:
    async def _do(app):
        async with app.state.db.read_session() as session:
            return (await session.get(IssueFileRow, file_id)).page_count

    return client.portal.call(_do, client.app)


def _pse_links(entry) -> list[dict]:
    return [
        {"href": el.get("href"), "count": el.get(f"{PSE}count")}
        for el in entry.findall(f"{ATOM}link")
        if el.get("rel") == REL_PSE_STREAM
    ]


# A ``.cbr`` file whose CONTENT is a ZIP with real image members: the content
# seam routes it to the ZIP opener, so the full render path runs against a
# misnamed archive (task 2.3 render + task 2.5 forward direction).
def _cbr_of_zip(pages: list[tuple[str, tuple[int, int]]]) -> bytes:
    return _zip_bytes([(name, _png(w, h)) for name, (w, h) in pages])


# --- FRG-OPDS-016: page-stream parity through a .cbr path --------------------


@pytest.mark.req("FRG-OPDS-016")
def test_cbr_in_range_page_streams_an_image(client, tmp_path):
    cbr = _cbr_of_zip([("p1.png", (300, 200)), ("p2.png", (300, 200))])
    data = _seed(
        client, tmp_path, [_spec("Saga", 30, [{"name": "Saga 001.cbr", "data": cbr}])]
    )
    fid = data["series"][0]["issues"][0]["files"][0]["id"]

    resp = client.get(f"/opds/page/{fid}/0")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/")
    img = Image.open(io.BytesIO(resp.content))
    assert (img.width, img.height) == (300, 200)


@pytest.mark.req("FRG-OPDS-016")
def test_cbr_out_of_range_and_negative_page_return_4xx(client, tmp_path):
    cbr = _cbr_of_zip([("p1.png", (100, 100))])
    data = _seed(
        client, tmp_path, [_spec("Saga", 31, [{"name": "Saga 001.cbr", "data": cbr}])]
    )
    fid = data["series"][0]["issues"][0]["files"][0]["id"]

    assert client.get(f"/opds/page/{fid}/0").status_code == 200
    assert client.get(f"/opds/page/{fid}/5").status_code == 404
    assert 400 <= client.get(f"/opds/page/{fid}/-1").status_code < 500


@pytest.mark.req("FRG-OPDS-016")
def test_cbr_width_bounds_the_returned_image(client, tmp_path):
    cbr = _cbr_of_zip([("p1.png", (400, 200))])
    data = _seed(
        client, tmp_path, [_spec("Saga", 32, [{"name": "Saga 001.cbr", "data": cbr}])]
    )
    fid = data["series"][0]["issues"][0]["files"][0]["id"]

    resp = client.get(f"/opds/page/{fid}/0", params={"width": 100})
    assert resp.status_code == 200
    assert Image.open(io.BytesIO(resp.content)).width <= 100


@pytest.mark.req("FRG-OPDS-016")
def test_cbr_feed_carries_pse_link_with_accurate_count(client, tmp_path):
    cbr = _cbr_of_zip([("p1.png", (80, 80)), ("p2.png", (80, 80)), ("p3.png", (80, 80))])
    data = _seed(
        client, tmp_path, [_spec("Saga", 33, [{"name": "Saga 001.cbr", "data": cbr}])]
    )
    series_id = data["series"][0]["id"]
    fid = data["series"][0]["issues"][0]["files"][0]["id"]
    _set_page_count(client, fid, 3)  # producer-cached (as the CBZ path would be)

    feed = ET.fromstring(client.get(f"/opds/series/{series_id}").text)
    (entry,) = [
        e
        for e in feed.findall(f"{ATOM}entry")
        if e.find(f"{ATOM}id").text == f"/opds/file/{fid}"
    ]
    pse = _pse_links(entry)
    assert len(pse) == 1
    assert pse[0]["count"] == "3"
    assert pse[0]["href"] == f"/opds/page/{fid}/{{pageNumber}}?width={{maxWidth}}"


# --- FRG-OPDS-016: NULL page_count heals lazily on first stream (task 2.4) ----


@pytest.mark.req("FRG-OPDS-016")
def test_cbr_null_page_count_heals_lazily_on_first_stream(client, tmp_path):
    """A pre-existing CBR row with page_count NULL carries no PSE link; the first
    stream lists the archive, persists the count, and the feed then emits PSE with
    zero further archive I/O (the count is read straight off the row)."""
    cbr = _cbr_of_zip([("p1.png", (60, 40)), ("p2.png", (60, 40))])
    data = _seed(
        client, tmp_path, [_spec("Saga", 34, [{"name": "Saga 001.cbr", "data": cbr}])]
    )
    series_id = data["series"][0]["id"]
    fid = data["series"][0]["issues"][0]["files"][0]["id"]
    _set_page_count(client, fid, None)  # imported before RAR support → NULL

    # Before any stream: NULL count → no PSE link in the feed.
    feed_before = ET.fromstring(client.get(f"/opds/series/{series_id}").text)
    (entry_before,) = [
        e
        for e in feed_before.findall(f"{ATOM}entry")
        if e.find(f"{ATOM}id").text == f"/opds/file/{fid}"
    ]
    assert _pse_links(entry_before) == []

    # First stream heals the row.
    assert client.get(f"/opds/page/{fid}/0").status_code == 200
    assert _read_page_count(client, fid) == 2

    # Subsequent feed render emits PSE from the healed row (feed does no archive I/O).
    feed_after = ET.fromstring(client.get(f"/opds/series/{series_id}").text)
    (entry_after,) = [
        e
        for e in feed_after.findall(f"{ATOM}entry")
        if e.find(f"{ATOM}id").text == f"/opds/file/{fid}"
    ]
    pse = _pse_links(entry_after)
    assert len(pse) == 1 and pse[0]["count"] == "2"


# --- FRG-OPDS-016: encrypted/unreadable RAR degrades, never errors (task 2.6) -


@pytest.mark.req("FRG-OPDS-016")
def test_encrypted_cbr_has_no_pse_and_stream_404s(client, tmp_path):
    """A real encrypted RAR on a ``.cbr`` path is non-listable: the feed carries no
    PSE link and its page stream 404s (the FRG-OPDS-008 non-listable degradation)
    — never an error feed."""
    enc = (_RAR_FIXTURES / "rar5-hpsw.rar").read_bytes()
    data = _seed(
        client, tmp_path, [_spec("Saga", 35, [{"name": "Saga 001.cbr", "data": enc}])]
    )
    series_id = data["series"][0]["id"]
    fid = data["series"][0]["issues"][0]["files"][0]["id"]

    # The whole-file download link is always present; no PSE stream link.
    feed = ET.fromstring(client.get(f"/opds/series/{series_id}").text)
    (entry,) = [
        e
        for e in feed.findall(f"{ATOM}entry")
        if e.find(f"{ATOM}id").text == f"/opds/file/{fid}"
    ]
    assert _pse_links(entry) == []
    assert client.get(f"/opds/page/{fid}/0").status_code == 404


# --- owner-fixture stub: true image-bearing RAR render ------------------------


@pytest.mark.req("FRG-OPDS-016")
@pytest.mark.skip(
    reason="TODO(owner-fixture): needs a comic-shaped image-bearing .cbr (RAR4+RAR5 "
    "with real PNG/JPEG pages). RAR creation is impossible in CI — the owner "
    "generates these with RARLAB's macOS-arm trial CLI on his host (recorded as an "
    "owner action item). The RAR read/list mechanics are proven against the vendored "
    "text-member fixtures in tests/security/test_archives_rar.py; the render pipeline "
    "against a .cbr path is proven via the ZIP-renamed-.cbr tests above. This stub is "
    "the last mile: decode an image extracted from a genuine RAR through /opds/page."
)
def test_true_rar_image_render_streams_page():  # pragma: no cover - skipped stub
    raise AssertionError("owner-fixture required")
