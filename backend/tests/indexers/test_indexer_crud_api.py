"""Indexer CRUD HTTP surface (FRG-IDX-001, FRG-IDX-002, FRG-API-009).

Completes the provider REST surface the change-7 settings UI is built against:
list / create / partial-update / delete on ``/api/v1/indexer``. The pre-existing
``/schema`` and ``/test`` endpoints are covered by ``test_indexer_api.py`` and
are not re-exercised here.

Secret discipline (FRG-API-009): the write-only ``api_key`` is NEVER present in
any GET/list/create/update response, a partial PUT that omits it KEEPS the
stored value, and a supplied one overrides it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from foragerr.app import create_app
from http_support import make_settings

SECRET = "dog-secret-key-9999"


@pytest.fixture
def settings(tmp_path: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    return make_settings(cfg)


@pytest.fixture
def client(settings):
    app = create_app(settings)
    with TestClient(app) as c:
        # First-run seeding (FRG-DEP-013) provisions a default GetComics indexer
        # at startup. Delete any seeded rows so these CRUD tests exercise a clean
        # slate; the persisted seed marker stays set, so nothing is re-seeded.
        for row in c.get("/api/v1/indexer").json():
            c.delete(f"/api/v1/indexer/{row['id']}")
        yield c


def _create_body(**overrides):
    body = {
        "implementation": "newznab",
        "name": "DogNZB",
        "settings": {
            "base_url": "https://api.dognzb.cr",
            "api_key": SECRET,
            "categories": [7030],
        },
    }
    body.update(overrides)
    return body


async def _stored_settings(app, indexer_id: int) -> dict | None:
    """Read the persisted settings JSON with secret fields DECRYPTED, for
    assertions that a write-only secret survived an edit — it can never be
    observed via the API by design. Secrets are encrypted at rest
    (``enc:v1:``, FRG-AUTH-008); ``decrypt_secret`` reveals them here (and
    passes plaintext through), so the survival assertions compare against the
    original value while at-rest encryption is proven separately."""
    from foragerr.indexers.repo import get_indexer
    from foragerr.keystore import decrypt_secret

    row = await get_indexer(app.state.db, indexer_id)
    if row is None:
        return None
    return {
        key: (decrypt_secret(value) if isinstance(value, str) else value)
        for key, value in json.loads(row.settings).items()
    }


# --- create / list round-trip ------------------------------------------------


@pytest.mark.req("FRG-IDX-001")
def test_create_then_list_round_trips_without_secret(client):
    resp = client.post("/api/v1/indexer", json=_create_body())
    assert resp.status_code == 201
    created = resp.json()
    assert created["id"] >= 1
    assert created["name"] == "DogNZB"
    assert created["implementation"] == "newznab"
    assert created["protocol"] == "usenet"
    # Secret never echoed; public settings survive.
    assert "api_key" not in created["settings"]
    assert created["settings"]["base_url"] == "https://api.dognzb.cr"

    listed = client.get("/api/v1/indexer")
    assert listed.status_code == 200
    rows = listed.json()
    assert [r["id"] for r in rows] == [created["id"]]
    assert "api_key" not in rows[0]["settings"]


@pytest.mark.req("FRG-API-009")
def test_secret_is_never_serialized_by_get_or_create(client):
    created = client.post("/api/v1/indexer", json=_create_body()).json()
    listed = client.get("/api/v1/indexer")
    # The raw secret material appears in no response body anywhere.
    assert SECRET not in json.dumps(created)
    assert SECRET not in listed.text


@pytest.mark.req("FRG-IDX-002")
def test_create_persists_the_three_usage_toggles(client):
    resp = client.post(
        "/api/v1/indexer",
        json=_create_body(enable_rss=False, enable_auto=True, enable_interactive=False),
    )
    body = resp.json()
    assert body["enable_rss"] is False
    assert body["enable_auto"] is True
    assert body["enable_interactive"] is False


# --- partial update / secret survival ----------------------------------------


@pytest.mark.req("FRG-API-009")
def test_put_omitting_secret_keeps_the_stored_value(client):
    created = client.post("/api/v1/indexer", json=_create_body()).json()
    # Change base_url only; api_key deliberately omitted (write-only "keep").
    resp = client.put(
        f"/api/v1/indexer/{created['id']}",
        json={"settings": {"base_url": "https://new.dognzb.cr", "categories": [7030]}},
    )
    assert resp.status_code == 200
    assert resp.json()["settings"]["base_url"] == "https://new.dognzb.cr"
    assert "api_key" not in resp.json()["settings"]
    # Ground truth: the stored secret is unchanged.
    stored = client.portal.call(_stored_settings, client.app, created["id"])
    assert stored["api_key"] == SECRET
    assert stored["base_url"] == "https://new.dognzb.cr"


@pytest.mark.req("FRG-API-009")
def test_put_supplying_secret_overrides_the_stored_value(client):
    created = client.post("/api/v1/indexer", json=_create_body()).json()
    resp = client.put(
        f"/api/v1/indexer/{created['id']}",
        json={
            "settings": {
                "base_url": "https://api.dognzb.cr",
                "api_key": "rotated-key-0001",
                "categories": [7030],
            }
        },
    )
    assert resp.status_code == 200
    stored = client.portal.call(_stored_settings, client.app, created["id"])
    assert stored["api_key"] == "rotated-key-0001"


@pytest.mark.req("FRG-IDX-002")
def test_put_toggle_only_leaves_name_and_settings_untouched(client):
    created = client.post("/api/v1/indexer", json=_create_body()).json()
    resp = client.put(f"/api/v1/indexer/{created['id']}", json={"enabled": False})
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert body["name"] == "DogNZB"  # untouched
    assert body["settings"]["base_url"] == "https://api.dognzb.cr"  # untouched
    # The stored secret is still intact after a non-settings PUT.
    stored = client.portal.call(_stored_settings, client.app, created["id"])
    assert stored["api_key"] == SECRET


# --- delete ------------------------------------------------------------------


@pytest.mark.req("FRG-IDX-001")
def test_delete_removes_the_indexer(client):
    created = client.post("/api/v1/indexer", json=_create_body()).json()
    assert client.delete(f"/api/v1/indexer/{created['id']}").status_code == 204
    assert client.get("/api/v1/indexer").json() == []


# --- not-found + validation error shape --------------------------------------


@pytest.mark.req("FRG-IDX-001")
def test_put_unknown_id_is_404(client):
    resp = client.put("/api/v1/indexer/999", json={"enabled": False})
    assert resp.status_code == 404


@pytest.mark.req("FRG-IDX-001")
def test_delete_unknown_id_is_404(client):
    assert client.delete("/api/v1/indexer/999").status_code == 404


@pytest.mark.req("FRG-IDX-001")
def test_create_invalid_settings_is_field_precise_400(client):
    resp = client.post(
        "/api/v1/indexer",
        json={"implementation": "newznab", "name": "x", "settings": {"api_key": "k"}},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert set(body) == {"message", "errors"}
    assert body["errors"][0]["field"] == "settings.base_url"


@pytest.mark.req("FRG-IDX-001")
def test_create_unknown_implementation_is_400(client):
    resp = client.post(
        "/api/v1/indexer",
        json={"implementation": "torznab", "name": "x", "settings": {}},
    )
    assert resp.status_code == 400
    assert resp.json()["errors"][0]["field"] == "implementation"


@pytest.mark.req("FRG-API-009")
def test_put_invalid_merged_settings_is_field_precise_400(client):
    created = client.post("/api/v1/indexer", json=_create_body()).json()
    # An empty category list violates the settings contract on merge.
    resp = client.put(
        f"/api/v1/indexer/{created['id']}",
        json={"settings": {"categories": []}},
    )
    assert resp.status_code == 400
    assert resp.json()["errors"][0]["field"] == "settings.categories"
