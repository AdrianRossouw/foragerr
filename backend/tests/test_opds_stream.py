"""OPDS-PSE page-stream + local-cover route tests (FRG-OPDS-008, FRG-OPDS-011).

Real CBZ archives with genuine JPEG image members are seeded on disk so the
stream/cover endpoints exercise the whole list -> read -> decode -> downscale
path against actual bytes — never a fabricated path the way a hostile client
would try. Page counts are set on the row the way the import producer (area C)
does, so the feed read stays zero-archive-I/O.
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
from foragerr.library import repo
from opds_support import opds_settings, seed

ATOM = "{http://www.w3.org/2005/Atom}"
PSE = "{http://vaemendis.net/opds-pse/ns}"
REL_PSE_STREAM = "http://vaemendis.net/opds-pse/stream"
REL_IMAGE = "http://opds-spec.org/image"
REL_THUMBNAIL = "http://opds-spec.org/image/thumbnail"


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


def _jpeg(width: int, height: int, color=(120, 60, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, "JPEG")
    return buf.getvalue()


def _cbz_bytes(pages: list[tuple[str, tuple[int, int]]], *, extra=None) -> bytes:
    """A CBZ with real JPEG members. ``pages`` = [(name, (w, h)), ...];
    ``extra`` = optional [(name, bytes), ...] non-image members (e.g. ComicInfo)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, (w, h) in pages:
            zf.writestr(name, _jpeg(w, h))
        for name, data in extra or []:
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
    """Simulate the import producer caching ``page_count`` on the row."""

    async def _do(app):
        from foragerr.library.models import IssueFileRow

        async with app.state.db.write_session() as session:
            row = await session.get(IssueFileRow, file_id)
            row.page_count = count

    client.portal.call(_do, client.app)


def _links(entry) -> list[dict]:
    return [
        {"rel": el.get("rel"), "href": el.get("href"), "type": el.get("type"),
         "count": el.get(f"{PSE}count")}
        for el in entry.findall(f"{ATOM}link")
    ]


# --- FRG-OPDS-008: page stream endpoint -------------------------------------


@pytest.mark.req("FRG-OPDS-008")
def test_in_range_page_streams_an_image(client, tmp_path):
    cbz = _cbz_bytes([("p1.jpg", (300, 200)), ("p2.jpg", (300, 200))])
    data = _seed(client, tmp_path, [_spec("Saga", 1, [{"name": "Saga 001.cbz", "data": cbz}])])
    fid = data["series"][0]["issues"][0]["files"][0]["id"]

    resp = client.get(f"/opds/page/{fid}/0")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/")
    img = Image.open(io.BytesIO(resp.content))  # decodes as a real image
    assert (img.width, img.height) == (300, 200)


@pytest.mark.req("FRG-OPDS-008")
def test_out_of_range_and_negative_page_return_4xx(client, tmp_path):
    cbz = _cbz_bytes([("p1.jpg", (100, 100))])
    data = _seed(client, tmp_path, [_spec("Saga", 2, [{"name": "Saga 001.cbz", "data": cbz}])])
    fid = data["series"][0]["issues"][0]["files"][0]["id"]

    # page 0 exists; page 5 is past the end; a negative index never matches the
    # (unsigned) route converter — both are a bounded 4xx, never bytes.
    assert client.get(f"/opds/page/{fid}/0").status_code == 200
    assert client.get(f"/opds/page/{fid}/5").status_code == 404
    assert 400 <= client.get(f"/opds/page/{fid}/-1").status_code < 500


@pytest.mark.req("FRG-OPDS-008")
def test_width_bounds_the_returned_image(client, tmp_path):
    cbz = _cbz_bytes([("p1.jpg", (400, 200))])  # 2:1, wider than the request
    data = _seed(client, tmp_path, [_spec("Saga", 3, [{"name": "Saga 001.cbz", "data": cbz}])])
    fid = data["series"][0]["issues"][0]["files"][0]["id"]

    resp = client.get(f"/opds/page/{fid}/0", params={"width": 100})
    assert resp.status_code == 200
    img = Image.open(io.BytesIO(resp.content))
    assert img.width <= 100  # downscaled, never wider than requested


@pytest.mark.req("FRG-OPDS-008")
def test_stream_resolution_is_id_only(client, tmp_path):
    cbz = _cbz_bytes([("p1.jpg", (100, 100))])
    data = _seed(client, tmp_path, [_spec("Saga", 4, [{"name": "Saga 001.cbz", "data": cbz}])])
    fid = data["series"][0]["issues"][0]["files"][0]["id"]
    issue_id = data["series"][0]["issues"][0]["id"]

    # A bogus id -> 404. A non-integer id -> 4xx at the type boundary (no path).
    assert client.get("/opds/page/999999/0").status_code == 404
    assert 400 <= client.get("/opds/page/not-an-int/0").status_code < 500

    # A foreign row whose path escaped every managed root is a 404 — the same
    # containment refusal the whole-file download applies (FRG-OPDS-003).
    outside = tmp_path / "outside" / "secret.cbz"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_bytes(cbz)

    async def _add_rogue(app):
        async with app.state.db.write_session() as session:
            row = await repo.add_issue_file(
                session, issue_id=issue_id, path=str(outside), size=len(cbz)
            )
            return row.id

    rogue_id = client.portal.call(_add_rogue, client.app)
    assert client.get(f"/opds/page/{rogue_id}/0").status_code == 404


@pytest.mark.req("FRG-OPDS-008")
def test_feed_carries_pse_link_only_for_a_listable_issue(client, tmp_path):
    listable = _cbz_bytes([("p1.jpg", (80, 80)), ("p2.jpg", (80, 80)), ("p3.jpg", (80, 80))])
    spec = _spec(
        "Saga", 5,
        [
            {"name": "Saga 001.cbz", "data": listable},   # listable CBZ
            {"name": "Saga 002.cbr", "data": b"Rar!\x1a\x07\x00 junk-not-listable"},
        ],
    )
    data = _seed(client, tmp_path, [spec])
    series_id = data["series"][0]["id"]
    listable_id = data["series"][0]["issues"][0]["files"][0]["id"]
    nonlistable_id = data["series"][0]["issues"][1]["files"][0]["id"]

    # The import producer caches the count for the listable file; the CBR stays
    # NULL (unlistable). The feed reads the row only — no archive is opened.
    _set_page_count(client, listable_id, 3)
    _set_page_count(client, nonlistable_id, None)

    feed = ET.fromstring(client.get(f"/opds/series/{series_id}").text)
    entries = {e.find(f"{ATOM}id").text: e for e in feed.findall(f"{ATOM}entry")}

    listable_links = _links(entries[f"/opds/file/{listable_id}"])
    pse = [ln for ln in listable_links if ln["rel"] == REL_PSE_STREAM]
    assert len(pse) == 1
    assert pse[0]["count"] == "3"  # pse:count from the cached count
    assert pse[0]["href"] == f"/opds/page/{listable_id}/{{pageNumber}}?width={{maxWidth}}"

    nonlistable_links = _links(entries[f"/opds/file/{nonlistable_id}"])
    assert [ln for ln in nonlistable_links if ln["rel"] == REL_PSE_STREAM] == []


# --- FRG-OPDS-011: local first-page cover fallback --------------------------


@pytest.mark.req("FRG-OPDS-011")
def test_coverless_issue_points_image_links_at_local_cover(client, tmp_path):
    cbz = _cbz_bytes([("p1.jpg", (200, 300))])
    data = _seed(client, tmp_path, [_spec("Saga", 6, [{"name": "Saga 001.cbz", "data": cbz}])])
    fid = data["series"][0]["issues"][0]["files"][0]["id"]
    series_id = data["series"][0]["id"]

    body = client.get(f"/opds/series/{series_id}").text
    (entry,) = ET.fromstring(body).findall(f"{ATOM}entry")
    rels = {ln["rel"]: ln["href"] for ln in _links(entry) if ln["rel"] and "image" in ln["rel"]}
    # No remote ComicVine cover cached -> the local per-file cover endpoint.
    assert rels[REL_IMAGE] == f"/opds/cover/{fid}"
    assert rels[REL_THUMBNAIL] == f"/opds/cover/{fid}?thumbnail"
    # No remote CDN host leaks into the feed (only namespace/rel URIs carry a
    # scheme, and none of them are an image host).
    for host in ("comicvine", "gamespot", "cbsistatic"):
        assert host not in body.lower()


@pytest.mark.req("FRG-OPDS-011")
def test_local_cover_serves_page_one_extracted_locally(client, tmp_path):
    cbz = _cbz_bytes([("aaa_first.jpg", (200, 300)), ("zzz_last.jpg", (50, 50))])
    data = _seed(client, tmp_path, [_spec("Saga", 7, [{"name": "Saga 001.cbz", "data": cbz}])])
    fid = data["series"][0]["issues"][0]["files"][0]["id"]

    resp = client.get(f"/opds/cover/{fid}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    img = Image.open(io.BytesIO(resp.content))  # a real, locally-extracted image
    # page one (natural order) is the 200x300 source; the cover width is bounded.
    assert img.width <= 640
    assert img.height >= img.width  # portrait aspect preserved (was 2:3)

    # A second request is served from the on-disk cache (still a valid image).
    again = client.get(f"/opds/cover/{fid}")
    assert again.status_code == 200
    Image.open(io.BytesIO(again.content))


@pytest.mark.req("FRG-OPDS-011")
def test_local_cover_thumbnail_served_locally_and_smaller(client, tmp_path):
    cbz = _cbz_bytes([("p1.jpg", (600, 900))])
    data = _seed(client, tmp_path, [_spec("Saga", 8, [{"name": "Saga 001.cbz", "data": cbz}])])
    fid = data["series"][0]["issues"][0]["files"][0]["id"]

    full = client.get(f"/opds/cover/{fid}")
    thumb = client.get(f"/opds/cover/{fid}", params={"thumbnail": ""})
    assert full.status_code == thumb.status_code == 200
    assert thumb.headers["content-type"] == "image/jpeg"
    full_img = Image.open(io.BytesIO(full.content))
    thumb_img = Image.open(io.BytesIO(thumb.content))
    assert thumb_img.width <= 256
    assert thumb_img.width < full_img.width  # the thumbnail is the smaller render


@pytest.mark.req("FRG-OPDS-011")
def test_local_cover_unknown_id_is_404(client, tmp_path):
    _seed(client, tmp_path, [_spec("Saga", 9, [{"name": "Saga 001.cbz", "data": _cbz_bytes([("p1.jpg", (10, 10))])}])])
    assert client.get("/opds/cover/999999").status_code == 404
