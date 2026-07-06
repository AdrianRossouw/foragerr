"""Download-client CRUD HTTP surface (FRG-DL-002, FRG-API-009).

Completes the provider REST surface the change-7 settings UI is built against:
list / create / partial-update / delete on ``/api/v1/downloadclient``, mirroring
the indexer CRUD contract. The pre-existing ``/schema`` and ``/test`` endpoints
are covered by ``test_provider_api.py`` and are not re-exercised here.

FRG-DL-002 ("Client configuration and selection") is the governing config
requirement; FRG-DL-003 ("SABnzbd add via file upload") concerns grab dispatch,
not configuration, so it is intentionally NOT cited here.

Secret discipline (FRG-API-009): the write-only ``api_key`` is never echoed, a
partial PUT that omits it keeps the stored value, a supplied one overrides it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from foragerr.app import create_app
from http_support import make_settings

SECRET = "sab-secret-key-4321"


@pytest.fixture
def settings(tmp_path: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    return make_settings(cfg)


@pytest.fixture
def client(settings):
    app = create_app(settings)
    with TestClient(app) as c:
        # First-run seeding (FRG-DEP-013) provisions a default built-in DDL
        # client at startup. Delete any seeded rows so these CRUD tests exercise
        # a clean slate; the persisted seed marker stays set, so nothing is
        # re-seeded.
        for row in c.get("/api/v1/downloadclient").json():
            c.delete(f"/api/v1/downloadclient/{row['id']}")
        yield c


def _create_body(**overrides):
    body = {
        "implementation": "sabnzbd",
        "name": "SABnzbd",
        "settings": {
            "base_url": "http://sab:8080",
            "api_key": SECRET,
            "category": "comics",
        },
    }
    body.update(overrides)
    return body


async def _stored_settings(app, client_id: int) -> dict | None:
    from foragerr.downloads.repo import get_download_client

    row = await get_download_client(app.state.db, client_id)
    return json.loads(row.settings) if row is not None else None


# --- create / list -----------------------------------------------------------


@pytest.mark.req("FRG-DL-002")
def test_create_then_list_round_trips_without_secret(client):
    resp = client.post("/api/v1/downloadclient", json=_create_body())
    assert resp.status_code == 201
    created = resp.json()
    assert created["name"] == "SABnzbd"
    assert created["implementation"] == "sabnzbd"
    assert created["protocol"] == "usenet"
    assert created["remove_completed_downloads"] is True
    assert "api_key" not in created["settings"]
    assert created["settings"]["base_url"] == "http://sab:8080"

    rows = client.get("/api/v1/downloadclient").json()
    assert [r["id"] for r in rows] == [created["id"]]
    assert "api_key" not in rows[0]["settings"]


@pytest.mark.req("FRG-API-009")
def test_secret_is_never_serialized_by_get_or_create(client):
    created = client.post("/api/v1/downloadclient", json=_create_body()).json()
    listed = client.get("/api/v1/downloadclient")
    assert SECRET not in json.dumps(created)
    assert SECRET not in listed.text


@pytest.mark.req("FRG-DL-002")
def test_create_persists_remove_completed_flag(client):
    resp = client.post(
        "/api/v1/downloadclient",
        json=_create_body(remove_completed_downloads=False),
    )
    assert resp.json()["remove_completed_downloads"] is False


@pytest.mark.req("FRG-DL-002")
def test_create_ddl_client_has_no_secret(client):
    """The ``ddl`` implementation carries no secret; it round-trips fully."""
    resp = client.post(
        "/api/v1/downloadclient",
        json={"implementation": "ddl", "name": "GetComics", "settings": {}},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["protocol"] == "ddl"
    assert body["settings"]["prefer_upscaled"] is True  # model default applied


# --- partial update / secret survival ----------------------------------------


@pytest.mark.req("FRG-API-009")
def test_put_omitting_secret_keeps_the_stored_value(client):
    created = client.post("/api/v1/downloadclient", json=_create_body()).json()
    resp = client.put(
        f"/api/v1/downloadclient/{created['id']}",
        json={"settings": {"base_url": "http://sab2:8080", "category": "comics"}},
    )
    assert resp.status_code == 200
    assert resp.json()["settings"]["base_url"] == "http://sab2:8080"
    assert "api_key" not in resp.json()["settings"]
    stored = client.portal.call(_stored_settings, client.app, created["id"])
    assert stored["api_key"] == SECRET
    assert stored["base_url"] == "http://sab2:8080"


@pytest.mark.req("FRG-API-009")
def test_put_supplying_secret_overrides_the_stored_value(client):
    created = client.post("/api/v1/downloadclient", json=_create_body()).json()
    resp = client.put(
        f"/api/v1/downloadclient/{created['id']}",
        json={
            "settings": {
                "base_url": "http://sab:8080",
                "api_key": "rotated-sab-key",
                "category": "comics",
            }
        },
    )
    assert resp.status_code == 200
    stored = client.portal.call(_stored_settings, client.app, created["id"])
    assert stored["api_key"] == "rotated-sab-key"


@pytest.mark.req("FRG-DL-002")
def test_put_toggle_only_leaves_settings_untouched(client):
    created = client.post("/api/v1/downloadclient", json=_create_body()).json()
    resp = client.put(
        f"/api/v1/downloadclient/{created['id']}", json={"enabled": False}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert body["name"] == "SABnzbd"
    assert body["settings"]["base_url"] == "http://sab:8080"
    stored = client.portal.call(_stored_settings, client.app, created["id"])
    assert stored["api_key"] == SECRET


# --- delete + not-found + validation -----------------------------------------


@pytest.mark.req("FRG-DL-002")
def test_delete_removes_the_client(client):
    created = client.post("/api/v1/downloadclient", json=_create_body()).json()
    assert client.delete(f"/api/v1/downloadclient/{created['id']}").status_code == 204
    assert client.get("/api/v1/downloadclient").json() == []


@pytest.mark.req("FRG-DL-002")
def test_put_unknown_id_is_404(client):
    assert client.put("/api/v1/downloadclient/999", json={"enabled": False}).status_code == 404


@pytest.mark.req("FRG-DL-002")
def test_delete_unknown_id_is_404(client):
    assert client.delete("/api/v1/downloadclient/999").status_code == 404


@pytest.mark.req("FRG-DL-002")
def test_create_invalid_settings_is_field_precise_400(client):
    resp = client.post(
        "/api/v1/downloadclient",
        json={"implementation": "sabnzbd", "name": "x", "settings": {"api_key": "k"}},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert set(body) == {"message", "errors"}
    assert body["errors"][0]["field"] == "settings.base_url"


@pytest.mark.req("FRG-DL-002")
def test_create_unknown_implementation_is_400(client):
    resp = client.post(
        "/api/v1/downloadclient",
        json={"implementation": "nzbget", "name": "x", "settings": {}},
    )
    assert resp.status_code == 400
    assert resp.json()["errors"][0]["field"] == "implementation"
