"""Read-only root-folder + format-profile list endpoints (FRG-SER-008,
FRG-QUAL-001, FRG-UI-005).

These two GET collections back the add-series screen's Root Folder and Format
Profile pickers (FRG-UI-005), so it can offer real choices instead of raw id
inputs. FRG-QUAL-001 (the format-profile entity) is the id the list serves; the
add-flow need (FRG-UI-005) is why it exists as an endpoint. Both are plain
arrays (the sets are tiny) rather than the paging envelope.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from foragerr.app import create_app
from foragerr.library import repo
from foragerr.quality.models import DEFAULT_PROFILE_NAME
from http_support import make_settings


@pytest.fixture
def settings(tmp_path: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    return make_settings(cfg)


@pytest.fixture
def client(settings):
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


async def _create_root_folder(app, path: str) -> int:
    async with app.state.db.write_session() as session:
        row = await repo.create_root_folder(session, path)
        return row.id


# --- root folders ------------------------------------------------------------


@pytest.mark.req("FRG-SER-008")
def test_rootfolder_list_is_empty_before_any_are_configured(client):
    resp = client.get("/api/v1/rootfolder")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.req("FRG-SER-008")
def test_rootfolder_list_returns_configured_folders_with_free_space(client, tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    rid = client.portal.call(_create_root_folder, client.app, str(root))

    rows = client.get("/api/v1/rootfolder").json()
    assert len(rows) == 1
    assert rows[0]["id"] == rid
    assert rows[0]["path"] == str(root)
    # A real, existing path reports a non-negative free-space figure.
    assert isinstance(rows[0]["free_space"], int)
    assert rows[0]["free_space"] >= 0


@pytest.mark.req("FRG-SER-008")
def test_rootfolder_free_space_is_none_for_a_missing_path(client, tmp_path):
    missing = tmp_path / "gone"  # never created
    client.portal.call(_create_root_folder, client.app, str(missing))
    rows = client.get("/api/v1/rootfolder").json()
    assert rows[0]["free_space"] is None  # stat failure must not fail the list


# --- format profiles ---------------------------------------------------------


@pytest.mark.req("FRG-QUAL-001")
@pytest.mark.req("FRG-UI-005")
def test_formatprofile_list_includes_the_seeded_default(client):
    resp = client.get("/api/v1/formatprofile")
    assert resp.status_code == 200
    rows = resp.json()
    default = next(r for r in rows if r["name"] == DEFAULT_PROFILE_NAME)
    assert default["id"] >= 1
    # Ordered ladder + cutoff surface verbatim for the picker.
    assert default["formats"] == ["pdf", "cbr", "cbz"]
    assert default["cutoff"] == "cbz"
