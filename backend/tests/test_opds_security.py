"""OPDS security-by-construction tests: the download surface exposes no path
parameter (route-table inventory), id/page parameters reject injection
payloads at the type boundary, the OPDS module builds no SQL text from
request input, and the search feed's free-text term — the one hostile string
input on this unauthenticated listener — is inert: SQL metacharacters bound,
markup never reflected, oversized input bounded (FRG-OPDS-003, FRG-OPDS-004,
FRG-OPDS-007).
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient

import foragerr.opds.atom as atom_mod
import foragerr.opds.mime as mime_mod
import foragerr.opds.router as router_mod
from foragerr.app import create_app
from opds_support import opds_settings, seed, simple_series

ATOM = "{http://www.w3.org/2005/Atom}"


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


# --- FRG-OPDS-003: traversal unrepresentable (route-table inventory) --------


@pytest.mark.req("FRG-OPDS-003")
def test_opds_routes_declare_no_path_parameter(client):
    """Inventory every OPDS route from the OpenAPI schema: no route may declare
    a ``path``/``file``/``filename`` parameter, and every path parameter that
    exists must be an integer id — so a filesystem path is unrepresentable in
    the URL surface."""
    schema = client.app.openapi()
    opds_paths = {p: spec for p, spec in schema["paths"].items() if p.startswith("/opds")}
    assert opds_paths, "OPDS routes should be mounted"

    download_routes = []
    for path, spec in opds_paths.items():
        names = set(re.findall(r"{(\w+)}", path))
        # No path-shaped parameter anywhere in the URL template.
        assert names.isdisjoint({"path", "file", "filename", "filepath"}), path
        # Every declared path parameter is an integer id.
        for method_spec in spec.values():
            for param in method_spec.get("parameters", []):
                if param.get("in") == "path":
                    # id-only surface: every path parameter is an integer — the
                    # library id, series id, or the PSE 0-based page index (all
                    # ints, never a filesystem path). FRG-OPDS-003/008.
                    assert param["name"] in {
                        "issue_file_id",
                        "series_id",
                        "page",
                    }, path
                    assert param["schema"]["type"] == "integer", f"{path}:{param['name']}"
        if "/file/" in path:
            download_routes.append(path)

    # The single download route is id-only.
    assert download_routes == ["/opds/file/{issue_file_id}"]


# --- FRG-OPDS-004: injection payloads inert at the type boundary ------------


@pytest.mark.req("FRG-OPDS-004")
def test_injection_payloads_in_id_and_page_params_are_inert(client, tmp_path):
    data = client.portal.call(
        seed, client.app, tmp_path / "library", [simple_series(n_issues=2)]
    )
    series_id = data["series"][0]["id"]
    payload = '" OR 1=1 --'

    # id/page params are typed int: a SQL payload never reaches a query — it
    # is rejected at the type boundary (the app maps validation errors to 400).
    assert client.get(f"/opds/file/{payload}").status_code == 400
    assert client.get(f"/opds/series/{payload}").status_code == 400
    assert client.get("/opds/series", params={"page": payload}).status_code == 400

    # The database is untouched: a normal feed still returns exactly the real
    # rows (no injected "OR 1=1" row leak, no dropped data).
    feed = ET.fromstring(client.get(f"/opds/series/{series_id}").text)
    assert len(feed.findall(f"{ATOM}entry")) == 2


# --- FRG-OPDS-004: static check — no interpolated SQL ------------------------


@pytest.mark.req("FRG-OPDS-004")
def test_opds_module_builds_no_sql_text_from_input():
    """Static scan of the OPDS sources: no ``sqlalchemy.text``, no f-string /
    %-format / .format / concatenation building SQL — every query is an ORM
    ``select`` with bound parameters."""
    sql_kw = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|WHERE|ORDER\s+BY)\b", re.I)
    interp = re.compile(
        r"""(f["'].*?)"""  # f-string ...
        r"""|(%\s*\()"""  # %-formatting
        r"""|(\.format\s*\()""",  # .format(
    )
    for module in (router_mod, atom_mod, mime_mod):
        src = Path(module.__file__).read_text(encoding="utf-8")
        # No textual SQL construct at all.
        assert "text(" not in src.replace("context(", ""), module.__name__
        # No interpolation expression that also contains SQL keywords.
        for line in src.splitlines():
            code = line.split("#", 1)[0]  # ignore comments/docstring-ish text
            if interp.search(code) and sql_kw.search(code):
                raise AssertionError(f"possible interpolated SQL in {module.__name__}: {line!r}")
    # Positive: the router uses the ORM select() construct.
    assert "select(" in Path(router_mod.__file__).read_text(encoding="utf-8")


# --- FRG-OPDS-007: the search term is hostile input --------------------------


def _search(client, q: str):
    resp = client.get("/opds/search", params={"q": q})
    assert resp.status_code == 200, q  # never a 500, never a reject-with-reflection
    return resp


@pytest.mark.req("FRG-OPDS-007")
def test_search_sql_metacharacters_are_inert(client, tmp_path):
    data = client.portal.call(
        seed, client.app, tmp_path / "library",
        [simple_series("Saga", cv_volume_id=1, n_issues=2)],
    )
    series_id = data["series"][0]["id"]

    for payload in (
        "' OR 1=1 --",
        '"; DROP TABLE series; --',
        "saga' UNION SELECT * FROM issue_files --",
    ):
        feed = ET.fromstring(_search(client, payload).text)
        # A bound parameter: the payload matches nothing (or only a genuine
        # fold-containment hit) — it never becomes a tautology returning rows.
        hrefs = [e.find(f"{ATOM}id").text for e in feed.findall(f"{ATOM}entry")]
        assert hrefs in ([], [f"/opds/series/{series_id}"]), payload

    # LIKE wildcards are autoescaped: a bare '%' matches nothing rather than
    # every series (it would match all rows if bound unescaped into LIKE).
    feed = ET.fromstring(_search(client, "%").text)
    assert feed.findall(f"{ATOM}entry") == []

    # The database survived every payload: the real feed is intact.
    feed = ET.fromstring(client.get(f"/opds/series/{series_id}").text)
    assert len(feed.findall(f"{ATOM}entry")) == 2


@pytest.mark.req("FRG-OPDS-007")
def test_search_markup_in_query_is_never_reflected_unescaped(client, tmp_path):
    client.portal.call(
        seed, client.app, tmp_path / "library", [simple_series(n_issues=1)]
    )
    for payload in (
        "<script>alert(1)</script>",
        ']]></title><entry><id>evil</id>',
        '"><link href="http://evil/"/>',
    ):
        body = _search(client, payload).text
        assert "<script>" not in body, payload
        assert "evil" not in body or "http://evil/" not in body, payload
        feed = ET.fromstring(body)  # still well-formed XML
        # No entry was injected; the only entries are genuine series matches.
        for entry in feed.findall(f"{ATOM}entry"):
            assert entry.find(f"{ATOM}id").text.startswith("/opds/series/")


@pytest.mark.req("FRG-OPDS-007")
def test_search_oversized_query_is_bounded(client, tmp_path):
    client.portal.call(
        seed, client.app, tmp_path / "library", [simple_series(n_issues=1)]
    )
    resp = _search(client, "A" * 10_000)
    feed = ET.fromstring(resp.text)  # a normal, valid (here: empty) feed
    assert feed.findall(f"{ATOM}entry") == []

    # The trimmed term — not the 10k payload — is what pagination echoes:
    # every reflected q parameter is capped at the documented bound.
    for el in feed.findall(f"{ATOM}link"):
        query = parse_qs(urlsplit(el.get("href")).query)
        for value in query.get("q", []):
            assert len(value) <= router_mod.MAX_SEARCH_QUERY_LEN


# --- FRG-OPDS-012: the page/cover decode surface is bounded -----------------
# The stream/cover endpoints decode UNTRUSTED archive image bytes. A pixel-bomb
# (a real image whose declared dimensions exceed the pixel cap) and an oversized
# member (declared bytes over the per-page cap) must each yield a bounded, logged
# 4xx/5xx — never a hang, an OOM, or a crash. Both are proven via a tightened
# per-request cap so a small fixture trips the guard deterministically.


def _bomb_client(tmp_path: Path, **overrides):
    import io
    import zipfile

    from PIL import Image

    cfg = tmp_path / "cfg"
    cfg.mkdir()
    app = create_app(opds_settings(cfg, **overrides))

    def _cbz(width: int, height: int) -> bytes:
        img = io.BytesIO()
        Image.new("RGB", (width, height), (200, 60, 40)).save(img, "JPEG")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("page01.jpg", img.getvalue())
        return buf.getvalue()

    return app, _cbz


def _seed_one_cbz(client, tmp_path, cbz: bytes) -> int:
    import datetime as dt

    spec = {
        "title": "Bomb",
        "cv_volume_id": 4242,
        "issues": [
            {
                "cv_issue_id": 42421,
                "number": "1",
                "cover_date": dt.date(2012, 1, 1),
                "files": [{"name": "Bomb 001.cbz", "data": cbz}],
            }
        ],
    }
    data = client.portal.call(seed, client.app, tmp_path / "library", [spec])
    return data["series"][0]["issues"][0]["files"][0]["id"]


@pytest.mark.req("FRG-OPDS-012")
def test_pixel_bomb_page_returns_bounded_error(tmp_path):
    # A tiny 300x200 (60k px) image against a 100-pixel cap is a stand-in for a
    # decompression bomb: it is refused on its DECLARED dimensions before any
    # pixels are decoded.
    app, cbz = _bomb_client(tmp_path, opds_pse_max_pixels=100)
    with TestClient(app) as client:
        fid = _seed_one_cbz(client, tmp_path, cbz(300, 200))
        resp = client.get(f"/opds/page/{fid}/0")
        assert 400 <= resp.status_code < 600  # bounded, never a hang/crash
        assert resp.status_code != 200  # no oversized image bytes served
        assert not resp.headers.get("content-type", "").startswith("image/")


@pytest.mark.req("FRG-OPDS-012")
def test_oversized_member_page_returns_bounded_error(tmp_path):
    # A real JPEG whose declared decompressed size exceeds a tightened per-page
    # byte cap is refused before it is read (the zip-bomb guard), degrading to a
    # bounded 4xx/5xx rather than loading the member.
    app, cbz = _bomb_client(tmp_path, opds_pse_max_page_bytes=8)
    with TestClient(app) as client:
        fid = _seed_one_cbz(client, tmp_path, cbz(64, 64))
        resp = client.get(f"/opds/page/{fid}/0")
        assert 400 <= resp.status_code < 600
        assert resp.status_code != 200
        # The local cover extraction is bounded the same way (first-page read).
        cover = client.get(f"/opds/cover/{fid}")
        assert 400 <= cover.status_code < 600
