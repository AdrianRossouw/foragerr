"""OPDS feed contract tests: navigation/acquisition structure, non-empty
shelf rule, configurable base path, XML escaping, metadata sourcing, cover
links, and pagination with OpenSearch totals
(FRG-OPDS-001, FRG-OPDS-002, FRG-OPDS-006).
"""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from foragerr.app import create_app
from opds_support import opds_settings, seed, simple_series

ATOM = "{http://www.w3.org/2005/Atom}"
OS = "{http://a9.com/-/spec/opensearch/1.1/}"
NAV_KIND = "application/atom+xml; profile=opds-catalog; kind=navigation"
ACQ_KIND = "application/atom+xml; profile=opds-catalog; kind=acquisition"


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


def _seed(client, tmp_path, spec):
    return client.portal.call(seed, client.app, tmp_path / "library", spec)


def _links(feed_or_entry) -> list[dict]:
    return [
        {"rel": el.get("rel"), "type": el.get("type"), "href": el.get("href")}
        for el in feed_or_entry.findall(f"{ATOM}link")
    ]


# --- FRG-OPDS-001: navigation root & per-feed routes -----------------------


@pytest.mark.req("FRG-OPDS-001")
def test_root_feed_lists_only_non_empty_shelves(client, tmp_path):
    # Empty library: the root feed surfaces NO shelf (nothing has content).
    empty = client.get("/opds")
    assert empty.status_code == 200
    root = ET.fromstring(empty.text)
    assert root.findall(f"{ATOM}entry") == []

    # A series with issues-but-no-files: All Series has content (the default
    # shelf mirrors the full library, FRG-OPDS-018 owner amendment), Recent
    # does NOT (the non-empty convention applies per shelf).
    _seed(client, tmp_path, [simple_series(n_issues=0)])
    resp = client.get("/opds")
    assert resp.status_code == 200
    root = ET.fromstring(resp.text)
    entries = root.findall(f"{ATOM}entry")
    assert len(entries) == 1
    assert entries[0].find(f"{ATOM}title").text == "All Series"
    # The shelf link is a browse (navigation) feed.
    (link,) = _links(entries[0])
    assert link["type"] == NAV_KIND
    assert link["href"] == "/opds/series"
    # No empty shelves (Recent/Publishers/Story Arcs) appear.
    titles = {e.find(f"{ATOM}title").text for e in entries}
    assert titles == {"All Series"}

    # Once an issue FILE exists, the Recent shelf appears beside All Series.
    _seed(client, tmp_path / "more", [simple_series("Paper Girls", cv_volume_id=2)])
    root = ET.fromstring(client.get("/opds").text)
    titles = {e.find(f"{ATOM}title").text for e in root.findall(f"{ATOM}entry")}
    assert titles == {"All Series", "Recent Additions"}


@pytest.mark.req("FRG-OPDS-001")
def test_per_feed_routes_replace_cmd_dispatch(client, tmp_path):
    data = _seed(client, tmp_path, [simple_series()])
    series_id = data["series"][0]["id"]

    # root -> /opds/series -> /opds/series/{id}, each its own feed.
    root = ET.fromstring(client.get("/opds").text)
    shelf_href = root.find(f"{ATOM}entry/{ATOM}link").get("href")
    assert shelf_href == "/opds/series"

    shelf = ET.fromstring(client.get(shelf_href).text)
    entry_href = shelf.find(f"{ATOM}entry/{ATOM}link").get("href")
    assert entry_href == f"/opds/series/{series_id}"

    acq = client.get(entry_href)
    assert acq.status_code == 200
    # No ?cmd= dispatch anywhere in the URL surface.
    assert "cmd=" not in shelf_href and "cmd=" not in entry_href

    # A stray Mylar-style ?cmd= param is simply ignored (no dispatch exists).
    ignored = client.get("/opds", params={"cmd": "deliverFile", "file": "/etc/passwd"})
    assert ignored.status_code == 200


@pytest.mark.req("FRG-OPDS-001")
def test_acquisition_shelf_link_carries_acquisition_kind(client, tmp_path):
    _seed(client, tmp_path, [simple_series()])
    shelf = ET.fromstring(client.get("/opds/series").text)
    (entry,) = shelf.findall(f"{ATOM}entry")
    (link,) = _links(entry)
    # Per-series links resolve to a feed of downloadable issues -> acquisition.
    assert link["type"] == ACQ_KIND
    # ...distinct from the navigation kind used by the browse feed itself.
    assert ACQ_KIND != NAV_KIND


@pytest.mark.req("FRG-OPDS-001")
def test_base_path_is_configurable(tmp_path: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    settings = opds_settings(cfg, opds_base_path="/catalog")
    app = create_app(settings)
    with TestClient(app) as client:
        client.portal.call(seed, client.app, tmp_path / "library", [simple_series()])
        # Served at the configured base...
        resp = client.get("/catalog")
        assert resp.status_code == 200
        root = ET.fromstring(resp.text)
        assert root.find(f"{ATOM}entry/{ATOM}link").get("href") == "/catalog/series"
        # ...and the default /opds path is NOT served.
        assert client.get("/opds").status_code == 404


# --- FRG-OPDS-002: acquisition feed metadata, no archive I/O, covers -------


@pytest.mark.req("FRG-OPDS-002")
def test_entries_render_from_db_fields(client, tmp_path):
    data = _seed(client, tmp_path, [simple_series(n_issues=2)])
    series_id = data["series"][0]["id"]
    feed = ET.fromstring(client.get(f"/opds/series/{series_id}").text)
    entries = feed.findall(f"{ATOM}entry")
    assert len(entries) == 2
    for entry in entries:
        assert entry.find(f"{ATOM}title").text  # non-empty title
        assert entry.find(f"{ATOM}updated").text  # updated timestamp present
        assert entry.find(f"{ATOM}id").text.startswith("/opds/file/")


@pytest.mark.req("FRG-SRC-007")
def test_acquisition_feed_excludes_owned_via_edition_rows(client, tmp_path):
    """An owned-via-edition provenance row (size-0, edition_issue_id set) points
    at a shared collected file, not a distinct downloadable copy — it must NOT
    appear as an acquisition entry (no duplicate/size-0 entries, FRG-SRC-007)."""
    data = _seed(client, tmp_path, [simple_series(n_issues=2)])
    series_id = data["series"][0]["id"]
    real_issue_id = data["series"][0]["issues"][0]["id"]
    edition_issue_id = data["series"][0]["issues"][1]["id"]
    real_file_path = data["series"][0]["issues"][0]["files"][0]["path"]

    async def _add_edition_row(app):
        from foragerr.db.base import utcnow
        from foragerr.library.models import IssueFileRow

        async with app.state.db.write_session() as session:
            # An owned-via-edition marker for the OTHER issue, sharing the real
            # file's path with size 0 (the reconciliation shape).
            session.add(
                IssueFileRow(
                    issue_id=edition_issue_id,
                    path=real_file_path,
                    size=0,
                    edition_issue_id=real_issue_id,
                    added_at=utcnow(),
                )
            )

    client.portal.call(_add_edition_row, client.app)

    feed = ET.fromstring(client.get(f"/opds/series/{series_id}").text)
    entries = feed.findall(f"{ATOM}entry")
    # Only the two REAL single files are offered — the edition row is filtered.
    assert len(entries) == 2

    # And the recent feed likewise excludes the edition row.
    recent = ET.fromstring(client.get("/opds/recent").text)
    assert len(recent.findall(f"{ATOM}entry")) == 2


@pytest.mark.req("FRG-OPDS-002")
def test_cover_and_thumbnail_links_point_at_local_cache(client, tmp_path):
    data = _seed(client, tmp_path, [simple_series(n_issues=1)])
    series_id = data["series"][0]["id"]

    # A series WITH a cached ComicVine cover uses the OPDS-REALM series-cover
    # route for both image links (FRG-OPDS-019) — NOT the /api route, which an
    # OPDS reader's Basic credentials cannot reach; the cover-less
    # local-first-page fallback (FRG-OPDS-011) is covered in the stream suite.
    async def _mark_cover_cached(app):
        from foragerr.db.base import utcnow
        from foragerr.library.models import SeriesRow

        async with app.state.db.write_session() as session:
            row = await session.get(SeriesRow, series_id)
            row.cover_cached_at = utcnow()

    client.portal.call(_mark_cover_cached, client.app)

    body = client.get(f"/opds/series/{series_id}").text
    feed = ET.fromstring(body)
    (entry,) = feed.findall(f"{ATOM}entry")
    rels = {
        link["rel"]: link["href"]
        for link in _links(entry)
        if link["rel"] and "image" in link["rel"]
    }
    assert rels["http://opds-spec.org/image"] == f"/opds/series-cover/{series_id}"
    assert rels["http://opds-spec.org/image/thumbnail"] == f"/opds/series-cover/{series_id}"
    assert "/api/v1/series" not in body  # never the off-realm API route
    # No remote ComicVine/CDN image host leaks into the feed (only the Atom/
    # OPDS namespace + rel URIs legitimately contain a scheme).
    for host in ("comicvine", "gamespot", "cbsistatic"):
        assert host not in body.lower()


@pytest.mark.req("FRG-OPDS-002")
def test_zero_archive_io_at_feed_render(client, tmp_path, monkeypatch):
    """A 200-issue feed renders with an archive-open test double installed;
    the instrumentation must record zero opens of any archive file."""
    spec = simple_series(n_issues=200)
    data = _seed(client, tmp_path, [spec])
    series_id = data["series"][0]["id"]

    opened: list[str] = []
    import builtins

    real_open = builtins.open

    def recording_open(file, *args, **kwargs):
        name = str(file)
        if name.endswith((".cbz", ".cbr", ".pdf")):
            opened.append(name)
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", recording_open)

    # Page through the whole 200-issue series; NONE of it may open an archive.
    seen = 0
    page = 1
    while True:
        feed = ET.fromstring(
            client.get(f"/opds/series/{series_id}", params={"page": page, "count": 50}).text
        )
        n = len(feed.findall(f"{ATOM}entry"))
        seen += n
        if n < 50:
            break
        page += 1
    assert seen == 200
    assert opened == []


# --- FRG-OPDS-001/002: XML escaping of interpolated values -----------------


@pytest.mark.req("FRG-OPDS-001")
@pytest.mark.req("FRG-OPDS-002")
def test_injected_markup_in_titles_is_escaped_inert(client, tmp_path):
    hostile = '<script>alert(1)</script> & "OR 1=1 --"'
    spec = {
        "title": hostile,
        "cv_volume_id": 42,
        "issues": [
            {
                "cv_issue_id": 4242,
                "number": "1",
                "title": hostile,
                "files": [{"name": "x 001.cbz", "data": b"bytes"}],
            }
        ],
    }
    data = _seed(client, tmp_path, [spec])
    series_id = data["series"][0]["id"]

    shelf_body = client.get("/opds/series").text
    acq_body = client.get(f"/opds/series/{series_id}").text
    for body in (shelf_body, acq_body):
        # Raw markup never appears; the escaped entity does.
        assert "<script>" not in body
        assert "&lt;script&gt;" in body
        # Still well-formed XML that parses back to the exact original text.
        feed = ET.fromstring(body)
        assert feed.find(f".//{ATOM}entry/{ATOM}title").text == hostile


@pytest.mark.req("FRG-OPDS-002")
def test_control_chars_in_title_do_not_break_the_feed(client, tmp_path):
    """An XML-1.0-illegal control char (e.g. form-feed \\x0c) in a title must be
    stripped so the WHOLE feed stays well-formed — one poisoned title must not
    make a reader reject the entire page."""
    poisoned = "Bad\x0cTitle\x08End"  # form-feed + backspace: both XML-illegal
    spec = {
        "title": poisoned,
        "cv_volume_id": 77,
        "issues": [
            {
                "cv_issue_id": 7777,
                "number": "1",
                "title": poisoned,
                "files": [{"name": "x 001.cbz", "data": b"bytes"}],
            }
        ],
    }
    data = _seed(client, tmp_path, [spec])
    series_id = data["series"][0]["id"]

    for path in ("/opds/series", f"/opds/series/{series_id}"):
        body = client.get(path).text
        # The illegal chars are gone and the document parses (no raise).
        assert "\x0c" not in body and "\x08" not in body
        feed = ET.fromstring(body)  # would raise if the char slipped through
        title = feed.find(f".//{ATOM}entry/{ATOM}title").text
        assert title == "BadTitleEnd"


# --- FRG-OPDS-006: pagination + OpenSearch totals --------------------------


@pytest.mark.req("FRG-OPDS-006")
def test_multi_page_shelf_paginates_with_totals(client, tmp_path):
    spec = [simple_series(f"Series {i:02d}", cv_volume_id=i, n_issues=1) for i in range(1, 13)]
    _seed(client, tmp_path, spec)

    all_titles: list[str] = []
    for page in (1, 2, 3):
        feed = ET.fromstring(
            client.get("/opds/series", params={"page": page, "count": 5}).text
        )
        assert feed.find(f"{OS}totalResults").text == "12"
        assert feed.find(f"{OS}itemsPerPage").text == "5"
        assert feed.find(f"{OS}startIndex").text == str((page - 1) * 5 + 1)
        all_titles += [e.find(f"{ATOM}title").text for e in feed.findall(f"{ATOM}entry")]
    # Every entry reachable exactly once across the pages.
    assert len(all_titles) == 12
    assert len(set(all_titles)) == 12


@pytest.mark.req("FRG-OPDS-006")
def test_pagination_links_target_the_same_feed(client, tmp_path):
    """Mylar shipped next/prev links that pointed at the WRONG feed twice.
    Every nav link here must resolve back to the feed it paginates."""
    spec = [simple_series(f"S{i:02d}", cv_volume_id=i, n_issues=1) for i in range(1, 8)]
    _seed(client, tmp_path, spec)

    feed = ET.fromstring(client.get("/opds/series", params={"page": 2, "count": 3}).text)
    by_rel = {
        link["rel"]: link["href"]
        for link in _links(feed)
        if link["rel"] in {"first", "last", "next", "previous", "self"}
    }
    for rel, href in by_rel.items():
        assert href.split("?")[0] == "/opds/series", f"{rel} -> {href}"
    # Following next/previous lands on the expected pages.
    assert "page=3" in by_rel["next"]
    assert "page=1" in by_rel["previous"]
    assert "page=1" in by_rel["first"]
    assert "page=3" in by_rel["last"]  # 7 series / 3 per page -> 3 pages


@pytest.mark.req("FRG-OPDS-006")
def test_per_page_cap_is_enforced(client, tmp_path):
    spec = [simple_series(f"S{i:03d}", cv_volume_id=i, n_issues=1) for i in range(1, 130)]
    _seed(client, tmp_path, spec)
    # Ask for a page far above the configured cap (default 100).
    feed = ET.fromstring(
        client.get("/opds/series", params={"page": 1, "count": 99999}).text
    )
    assert feed.find(f"{OS}itemsPerPage").text == "100"
    assert len(feed.findall(f"{ATOM}entry")) == 100


def test_series_cover_route_serves_cached_bytes_with_head_parity(client, tmp_path):
    """The OPDS-realm series-cover route (FRG-OPDS-019) serves the cached
    cover the feed now points readers at, with HEAD parity and a 404 when
    absent — the bytes an OPDS client could not previously reach on /api."""
    data = _seed(client, tmp_path, [simple_series(n_issues=1)])
    series_id = data["series"][0]["id"]

    # Missing cover: deterministic 404 on both verbs.
    url = f"/opds/series-cover/{series_id}"
    assert client.get(url).status_code == 404
    assert client.head(url).status_code == 404

    # Write a cached cover exactly where the API route caches it.
    covers = Path(client.app.state.settings.config_dir) / "covers"
    covers.mkdir(parents=True, exist_ok=True)
    (covers / f"{series_id}.jpg").write_bytes(b"\xff\xd8\xff\xe0cover-bytes")

    get = client.get(url)
    assert get.status_code == 200
    assert get.headers["content-type"] == "image/jpeg"
    assert get.content == b"\xff\xd8\xff\xe0cover-bytes"
    head = client.head(url)
    assert head.status_code == 200
    assert head.headers["content-type"] == get.headers["content-type"]
    assert head.content == b""
