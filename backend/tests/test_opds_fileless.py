"""OPDS file-less series filtering (FRG-OPDS-018).

By default the All Series shelf mirrors the FULL library — wanted-but-fileless
series included (owner gate amendment, 2026-07-16). Enabling
``opds_hide_fileless_series`` opts into a reading-only shelf: series with no
downloadable files are omitted (M9 finding F23) and the root feed advertises
the All Series shelf only when it would list something.
"""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from foragerr.app import create_app
from opds_support import opds_settings, seed, simple_series

ATOM = "{http://www.w3.org/2005/Atom}"


def _fileless_series(title: str, cv_volume_id: int) -> dict:
    """A series that has issues but no imported files (the F23 empty shelf)."""
    return {
        "title": title,
        "cv_volume_id": cv_volume_id,
        "publisher": "Image",
        "issues": [
            {"cv_issue_id": cv_volume_id * 1000 + 1, "number": "1", "files": []}
        ],
    }


def _series_titles(client) -> list[str]:
    resp = client.get("/opds/series")
    assert resp.status_code == 200
    root = ET.fromstring(resp.text)
    return [e.find(f"{ATOM}title").text for e in root.findall(f"{ATOM}entry")]


def _root_entry_titles(client) -> set[str]:
    resp = client.get("/opds")
    assert resp.status_code == 200
    root = ET.fromstring(resp.text)
    return {e.find(f"{ATOM}title").text for e in root.findall(f"{ATOM}entry")}


def _make_client(settings):
    app = create_app(settings)
    return TestClient(app)


@pytest.mark.req("FRG-OPDS-018")
def test_fileless_series_render_by_default(tmp_path: Path):
    """Default: the shelf mirrors the library — wanted series included."""
    settings = opds_settings(tmp_path / "cfg")
    with _make_client(settings) as client:
        client.portal.call(
            seed,
            client.app,
            tmp_path / "library",
            [simple_series("HasFiles", 1), _fileless_series("EmptyShelf", 2)],
        )
        titles = _series_titles(client)
        assert "HasFiles" in titles
        assert "EmptyShelf" in titles


@pytest.mark.req("FRG-OPDS-018")
def test_opt_in_hiding_omits_fileless_series(tmp_path: Path):
    settings = opds_settings(tmp_path / "cfg", opds_hide_fileless_series=True)
    with _make_client(settings) as client:
        client.portal.call(
            seed,
            client.app,
            tmp_path / "library",
            [simple_series("HasFiles", 1), _fileless_series("EmptyShelf", 2)],
        )
        titles = _series_titles(client)
        assert "HasFiles" in titles
        assert "EmptyShelf" not in titles


@pytest.mark.req("FRG-OPDS-018")
def test_opt_in_hiding_gates_root_feed_advertisement(tmp_path: Path):
    """With hiding enabled and ONLY fileless series in the library, the root
    feed must not advertise an All Series shelf that opens empty (gate
    finding); by default the same library advertises it (shelf non-empty)."""
    hidden = opds_settings(tmp_path / "cfg-on", opds_hide_fileless_series=True)
    with _make_client(hidden) as client:
        client.portal.call(
            seed,
            client.app,
            tmp_path / "library-on",
            [_fileless_series("EmptyShelf", 3)],
        )
        assert "All Series" not in _root_entry_titles(client)

    default = opds_settings(tmp_path / "cfg-off")
    with _make_client(default) as client:
        client.portal.call(
            seed,
            client.app,
            tmp_path / "library-off",
            [_fileless_series("EmptyShelf", 4)],
        )
        assert "All Series" in _root_entry_titles(client)
