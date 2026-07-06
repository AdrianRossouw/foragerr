"""Recent Additions shelf contract tests (FRG-OPDS-013): newest-first by
IMPORT time (never release date), full acquisition entries identical to the
series shelf's, root-feed advertisement, and the shared page-size clamp.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from foragerr.app import create_app
from foragerr.library.models import IssueFileRow
from opds_support import opds_settings, seed, simple_series

ATOM = "{http://www.w3.org/2005/Atom}"
OS = "{http://a9.com/-/spec/opensearch/1.1/}"
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


async def _set_added_at(app, when_by_file_id: dict[int, dt.datetime]) -> None:
    async with app.state.db.write_session() as session:
        for file_id, when in when_by_file_id.items():
            await session.execute(
                update(IssueFileRow)
                .where(IssueFileRow.id == file_id)
                .values(added_at=when)
            )


def _entry_dict(entry) -> dict:
    return {
        "id": entry.find(f"{ATOM}id").text,
        "title": entry.find(f"{ATOM}title").text,
        "links": sorted(
            (el.get("rel"), el.get("type"), el.get("href"))
            for el in entry.findall(f"{ATOM}link")
        ),
    }


@pytest.mark.req("FRG-OPDS-013")
def test_recent_orders_by_import_time_not_release_date(client, tmp_path):
    """Release dates ASCEND with issue number, but issue 1 is imported LAST —
    the feed must lead with issue 1 (import time), not issue 3 (release)."""
    spec = simple_series(n_issues=3)
    for n, issue in enumerate(spec["issues"], start=1):
        issue["cover_date"] = dt.date(2012, n, 1)  # release order: 1 < 2 < 3
    data = _seed(client, tmp_path, [spec])
    files = [i["files"][0]["id"] for i in data["series"][0]["issues"]]
    # Import order (added_at): issue 2 first, then issue 3, issue 1 LAST.
    client.portal.call(
        _set_added_at,
        client.app,
        {
            files[1]: dt.datetime(2026, 7, 1, tzinfo=dt.timezone.utc),
            files[2]: dt.datetime(2026, 7, 2, tzinfo=dt.timezone.utc),
            files[0]: dt.datetime(2026, 7, 3, tzinfo=dt.timezone.utc),
        },
    )

    resp = client.get("/opds/recent")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/atom+xml")
    feed = ET.fromstring(resp.text)
    ids = [e.find(f"{ATOM}id").text for e in feed.findall(f"{ATOM}entry")]
    assert ids == [
        f"/opds/file/{files[0]}",  # newest import first, despite oldest release
        f"/opds/file/{files[2]}",
        f"/opds/file/{files[1]}",
    ]


@pytest.mark.req("FRG-OPDS-013")
def test_recent_entries_are_full_acquisition_entries(client, tmp_path):
    """Byte-for-byte the same entry richness as the series shelf: a reader can
    download straight from Recent."""
    data = _seed(client, tmp_path, [simple_series(n_issues=1)])
    series_id = data["series"][0]["id"]
    file_id = data["series"][0]["issues"][0]["files"][0]["id"]

    recent = ET.fromstring(client.get("/opds/recent").text)
    series_feed = ET.fromstring(client.get(f"/opds/series/{series_id}").text)
    (recent_entry,) = recent.findall(f"{ATOM}entry")
    (series_entry,) = series_feed.findall(f"{ATOM}entry")
    assert _entry_dict(recent_entry) == _entry_dict(series_entry)

    # The acquisition link itself: comic MIME type, id-only download href.
    acq = [
        el
        for el in recent_entry.findall(f"{ATOM}link")
        if el.get("rel") == "http://opds-spec.org/acquisition"
    ]
    assert len(acq) == 1
    assert acq[0].get("href") == f"/opds/file/{file_id}"
    assert "zip" in acq[0].get("type")  # .cbz -> the comic zip media type

    # The feed itself is an acquisition feed and the download really works.
    assert recent.find(f"{ATOM}title").text == "Recent Additions"
    download = client.get(f"/opds/file/{file_id}")
    assert download.status_code == 200


@pytest.mark.req("FRG-OPDS-013")
def test_recent_root_entry_and_page_size_clamp(client, tmp_path):
    _seed(client, tmp_path, [simple_series(n_issues=7)])

    # Root feed advertises the Recent shelf with the acquisition kind.
    root = ET.fromstring(client.get("/opds").text)
    recent_entries = [
        e
        for e in root.findall(f"{ATOM}entry")
        if e.find(f"{ATOM}title").text == "Recent Additions"
    ]
    assert len(recent_entries) == 1
    (link,) = recent_entries[0].findall(f"{ATOM}link")
    assert link.get("href") == "/opds/recent"
    assert link.get("type") == ACQ_KIND

    # Page-size clamping applies as on every feed (the shared pagination requirement shared cap).
    feed = ET.fromstring(
        client.get("/opds/recent", params={"page": 1, "count": 99999}).text
    )
    assert feed.find(f"{OS}itemsPerPage").text == "100"
    assert feed.find(f"{OS}totalResults").text == "7"

    # Pagination links point back at the Recent feed itself.
    page2 = ET.fromstring(
        client.get("/opds/recent", params={"page": 2, "count": 3}).text
    )
    for el in page2.findall(f"{ATOM}link"):
        if el.get("rel") in {"first", "last", "next", "previous", "self"}:
            assert el.get("href").split("?")[0] == "/opds/recent"
    assert len(page2.findall(f"{ATOM}entry")) == 3
