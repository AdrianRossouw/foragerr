"""OPDS-PSE page-stream + local-cover route tests (FRG-OPDS-008, FRG-OPDS-011).

Real CBZ archives with genuine JPEG image members are seeded on disk so the
stream/cover endpoints exercise the whole list -> read -> decode -> downscale
path against actual bytes — never a fabricated path the way a hostile client
would try. Page counts are set on the row the way the import producer (area C)
does, so the feed read stays zero-archive-I/O.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import io
import os
import threading
import time
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from foragerr.app import create_app
from foragerr.library import repo
from foragerr.library.models import IssueFileRow
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


def _jpeg_noise(width: int, height: int) -> bytes:
    """A NOISE (poorly-compressible) JPEG whose stored size far exceeds a small
    per-page byte cap — used to exercise the read-time per-page 502 path."""
    buf = io.BytesIO()
    Image.frombytes("RGB", (width, height), os.urandom(width * height * 3)).save(
        buf, "JPEG", quality=95
    )
    return buf.getvalue()


def _png_rgba(width: int, height: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (width, height), (10, 20, 30, 128)).save(buf, "PNG")
    return buf.getvalue()


def _zip_of(members: list[tuple[str, bytes]]) -> bytes:
    """A CBZ from explicit (name, bytes) members (bytes we do not want re-encoded
    the way ``_cbz_bytes`` regenerates JPEGs from dimensions)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members:
            zf.writestr(name, data)
    return buf.getvalue()


def _read_page_count(client, file_id: int) -> int | None:
    async def _do(app):
        async with app.state.db.read_session() as session:
            return (await session.get(IssueFileRow, file_id)).page_count

    return client.portal.call(_do, client.app)


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


# --- FIX-1b: listability decoupled from the tight per-page byte cap -----------


@pytest.mark.req("FRG-OPDS-008")
def test_oversized_page_does_not_404_the_whole_archive(tmp_path):
    """An archive that PASSED import must list all its pages at stream time even
    when one member exceeds the tight ``opds_pse_max_page_bytes``: listability is
    decoupled from the per-page cap (it stays at the default import cap), so a
    single oversized page is a per-page 502 while every other page still streams —
    NOT a whole-archive 404. Out-of-range still 404s, proving the archive listed."""
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    # A tiny per-page byte cap; the listing/import cap stays at the 256 MiB default.
    settings = opds_settings(cfg, opds_pse_max_page_bytes=8192)
    app = create_app(settings)
    with TestClient(app) as client:
        small = _jpeg(60, 40)  # well under 8 KiB
        big = _jpeg_noise(400, 400)  # noise → stored size >> 8 KiB
        assert len(small) < 8192 < len(big)
        cbz = _zip_of([("p1.jpg", small), ("p2.jpg", big)])
        data = _seed(
            client, tmp_path,
            [_spec("Saga", 20, [{"name": "Saga 001.cbz", "data": cbz}])],
        )
        fid = data["series"][0]["issues"][0]["files"][0]["id"]

        assert client.get(f"/opds/page/{fid}/0").status_code == 200  # small streams
        # The oversized page is refused at READ time with a bounded per-page 502…
        assert client.get(f"/opds/page/{fid}/1").status_code == 502
        # …but the archive itself listed BOTH pages: an out-of-range index 404s,
        # and the count was persisted as 2 (not None / whole-archive refusal).
        assert client.get(f"/opds/page/{fid}/2").status_code == 404
        assert _read_page_count(client, fid) == 2


# --- FIX-2: single listing per request + lazy write-back off the writer lock --


@pytest.mark.req("FRG-OPDS-009")
def test_first_stream_persists_count_and_lists_once(client, tmp_path, monkeypatch):
    """A first stream of a NULL-count issue persists the freshly-listed count, and
    the archive is listed AT MOST ONCE per request (no re-list, and no listing
    inside the write session / on the event loop)."""
    from foragerr.opds import router as opds_router

    cbz = _cbz_bytes([("p1.jpg", (60, 40)), ("p2.jpg", (60, 40))])
    data = _seed(
        client, tmp_path, [_spec("Saga", 21, [{"name": "Saga 001.cbz", "data": cbz}])]
    )
    fid = data["series"][0]["issues"][0]["files"][0]["id"]
    _set_page_count(client, fid, None)  # NULL → the lazy write-back path

    calls = {"n": 0}
    real = opds_router.list_image_members

    def _counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(opds_router, "list_image_members", _counting)

    assert client.get(f"/opds/page/{fid}/0").status_code == 200
    assert calls["n"] == 1  # listed exactly once per request (no re-list)
    assert _read_page_count(client, fid) == 2  # freshly-listed count persisted


# --- FIX-3: bounded concurrent renders (DoS) ---------------------------------


@pytest.mark.req("FRG-OPDS-012")
async def test_render_concurrency_is_bounded(monkeypatch):
    """Concurrent PSE renders are capped at ``_RENDER_CONCURRENCY``: an offload
    thread cannot be killed, so the semaphore is what bounds aggregate decode
    memory/threads. Block the render and prove no more than N run at once."""
    from foragerr.opds import router as opds_router

    active = 0
    peak = 0
    lock = threading.Lock()
    gate = threading.Event()

    def _blocking_render(data, *, max_width, max_pixels, force_jpeg=False):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        gate.wait(5.0)
        with lock:
            active -= 1
        return b"jpeg-bytes", "image/jpeg"

    monkeypatch.setattr(opds_router, "render_page", _blocking_render)

    class _Settings:
        opds_pse_max_pixels = 1_000_000
        opds_pse_request_timeout_seconds = 10.0

    n = opds_router._RENDER_CONCURRENCY
    tasks = [
        asyncio.ensure_future(
            opds_router._render_bounded(_Settings(), b"d", max_width=None, what="t")
        )
        for _ in range(n + 3)
    ]
    try:
        await asyncio.sleep(0.3)  # let all tasks reach the semaphore/render
        assert peak <= n  # never more than N renders live at once
    finally:
        gate.set()
        results = await asyncio.gather(*tasks)
    assert peak == n  # and the bound is genuinely reached (N ran together)
    assert all(r == (b"jpeg-bytes", "image/jpeg") for r in results)


# --- FIX-4: cache hit must not bypass id resolution/confinement ---------------


@pytest.mark.req("FRG-OPDS-011")
def test_cached_cover_not_served_when_source_no_longer_resolves(client, tmp_path):
    """A cached cover must NOT be served for an id whose source no longer resolves
    under a managed root (deleted / moved out): resolution+confinement runs BEFORE
    the cache is consulted, so a vanished source is a 404, never the stale image."""
    cbz = _cbz_bytes([("p1.jpg", (120, 160))])
    data = _seed(
        client, tmp_path, [_spec("Saga", 22, [{"name": "Saga 001.cbz", "data": cbz}])]
    )
    fid = data["series"][0]["issues"][0]["files"][0]["id"]
    src = Path(data["series"][0]["issues"][0]["files"][0]["path"])

    assert client.get(f"/opds/cover/{fid}").status_code == 200  # populates the cache
    src.unlink()  # the source archive is deleted / moved out of the library
    assert client.get(f"/opds/cover/{fid}").status_code == 404  # not the stale cover


# --- FIX-5: cover content-type truthfulness + source-change invalidation ------


@pytest.mark.req("FRG-OPDS-011")
def test_alpha_first_page_cover_served_as_jpeg(client, tmp_path):
    """An alpha (RGBA) first page yields a cover served as ``image/jpeg`` with real
    JPEG bytes — the cover path forces JPEG so the ``.jpg`` cache is never
    mislabeled PNG bytes."""
    cbz = _zip_of([("p1.png", _png_rgba(200, 300))])
    data = _seed(
        client, tmp_path, [_spec("Saga", 23, [{"name": "Saga 001.cbz", "data": cbz}])]
    )
    fid = data["series"][0]["issues"][0]["files"][0]["id"]

    resp = client.get(f"/opds/cover/{fid}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    img = Image.open(io.BytesIO(resp.content))
    assert img.format == "JPEG"  # truthful bytes, not mislabeled PNG


@pytest.mark.req("FRG-OPDS-011")
def test_cover_regenerated_after_source_changes(client, tmp_path):
    """The cover cache is invalidated when the source archive changes (newer
    mtime): a changed first page regenerates rather than serving forever-stale."""
    cbz = _zip_of([("p1.jpg", _jpeg(200, 300))])  # portrait first page
    data = _seed(
        client, tmp_path, [_spec("Saga", 24, [{"name": "Saga 001.cbz", "data": cbz}])]
    )
    fid = data["series"][0]["issues"][0]["files"][0]["id"]
    src = Path(data["series"][0]["issues"][0]["files"][0]["path"])

    first = client.get(f"/opds/cover/{fid}")
    assert first.status_code == 200
    img1 = Image.open(io.BytesIO(first.content))

    # Overwrite the source with a visibly different (landscape) first page and bump
    # its mtime clearly past the cache — the "source changed" signal.
    src.write_bytes(_zip_of([("p1.jpg", _jpeg(400, 200))]))
    future = time.time() + 100
    os.utime(src, (future, future))

    second = client.get(f"/opds/cover/{fid}")
    assert second.status_code == 200
    img2 = Image.open(io.BytesIO(second.content))
    assert (img2.width, img2.height) != (img1.width, img1.height)  # regenerated


# --- FIX-6: no PSE link for a 0-page archive ---------------------------------


@pytest.mark.req("FRG-OPDS-008")
def test_zero_page_count_emits_no_pse_link(client, tmp_path):
    """A ``page_count`` of 0 (a listable but image-less zip) emits NO PSE stream
    link — a 0-page link would promise pages a reader then cannot fetch."""
    cbz = _cbz_bytes([("p1.jpg", (50, 50))])
    data = _seed(
        client, tmp_path, [_spec("Saga", 25, [{"name": "Saga 001.cbz", "data": cbz}])]
    )
    fid = data["series"][0]["issues"][0]["files"][0]["id"]
    series_id = data["series"][0]["id"]
    _set_page_count(client, fid, 0)

    feed = ET.fromstring(client.get(f"/opds/series/{series_id}").text)
    (entry,) = feed.findall(f"{ATOM}entry")
    assert [ln for ln in _links(entry) if ln["rel"] == REL_PSE_STREAM] == []
