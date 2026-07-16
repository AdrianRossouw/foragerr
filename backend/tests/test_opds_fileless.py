"""OPDS file-less series filtering (FRG-OPDS-018).

The All Series feed omits series with no downloadable files by default, so a
reader browses only shelves that contain something to read (M9 finding F23:
freshly-added still-empty series rendered as empty shelves). A config opt-out
(``opds_hide_fileless_series=false``) restores them.
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


def _make_client(settings):
    app = create_app(settings)
    return TestClient(app)


@pytest.mark.req("FRG-OPDS-018")
def test_fileless_series_hidden_by_default(tmp_path: Path):
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
        assert "EmptyShelf" not in titles


@pytest.mark.req("FRG-OPDS-018")
def test_config_opt_out_lists_fileless_series(tmp_path: Path):
    settings = opds_settings(tmp_path / "cfg", opds_hide_fileless_series=False)
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
