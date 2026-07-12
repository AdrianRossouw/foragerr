"""Store-source connect/manage HTTP surface (FRG-SRC-001/002/003/005).

Cookie discipline (FRG-SRC-002): the cookie is validated live before persisting,
never echoed in any response, and a failed validation persists nothing.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from foragerr.app import create_app
from foragerr.sources import ratelimit
from sources_support import fixture_bytes, make_factory, order_handler
from http_support import make_settings

COOKIE = "PASTED-SESSION-COOKIE-xyz"


@pytest.fixture(autouse=True)
def _reset_gates():
    ratelimit.reset_gates()
    yield
    ratelimit.reset_gates()


@pytest.fixture
def settings(tmp_path: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    return make_settings(cfg)


def _install_factory(app, tmp_path, handler):
    factory = make_factory(tmp_path, httpx.MockTransport(handler))
    app.state.http_factory = factory
    return factory


@pytest.fixture
def client(settings):
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def _connect_body(**overrides):
    body = {"type": "humble", "settings": {"session_cookie": COOKIE}}
    body.update(overrides)
    return body


@pytest.mark.req("FRG-SRC-001")
def test_schema_lists_humble_with_secret_field(client):
    schema = client.get("/api/v1/sources/schema").json()
    humble = next(s for s in schema if s["type"] == "humble")
    cookie_field = next(f for f in humble["fields"] if f["name"] == "session_cookie")
    assert cookie_field["secret"] is True


@pytest.mark.req("FRG-SRC-002")
def test_connect_validates_live_and_reports_count(client, tmp_path):
    _install_factory(
        client.app, tmp_path, order_handler(list_body=fixture_bytes("order_list.json"))
    )
    resp = client.post("/api/v1/sources", json=_connect_body())
    assert resp.status_code == 201
    body = resp.json()
    assert body["order_count"] == 2
    assert body["message"] == "Connected — 2 order(s)"
    # The cookie is NEVER echoed back.
    assert "session_cookie" not in body["source"]["settings"]


@pytest.mark.req("FRG-SRC-002")
def test_connect_bad_cookie_persists_nothing(client, tmp_path):
    _install_factory(client.app, tmp_path, order_handler(list_status=401, list_body=b"{}"))
    resp = client.post("/api/v1/sources", json=_connect_body())
    assert resp.status_code == 400
    assert resp.json()["errors"][0]["field"] == "settings.session_cookie"
    # Nothing was persisted.
    assert client.get("/api/v1/sources").json() == []


@pytest.mark.req("FRG-SRC-002")
def test_cookie_absent_from_every_list_response(client, tmp_path):
    _install_factory(
        client.app, tmp_path, order_handler(list_body=fixture_bytes("order_list.json"))
    )
    client.post("/api/v1/sources", json=_connect_body())
    listing = client.get("/api/v1/sources").json()
    assert len(listing) == 1
    assert "session_cookie" not in listing[0]["settings"]
    assert COOKIE not in resp_text(listing)


@pytest.mark.req("FRG-SRC-002")
def test_reserved_prefix_cookie_rejected(client, tmp_path):
    _install_factory(
        client.app, tmp_path, order_handler(list_body=fixture_bytes("order_list.json"))
    )
    resp = client.post(
        "/api/v1/sources",
        json=_connect_body(settings={"session_cookie": "enc:v1:forged"}),
    )
    assert resp.status_code == 422


@pytest.mark.req("FRG-SRC-001")
def test_disconnect_keeps_source_row_clears_credential(client, tmp_path):
    _install_factory(
        client.app, tmp_path, order_handler(list_body=fixture_bytes("order_list.json"))
    )
    created = client.post("/api/v1/sources", json=_connect_body()).json()
    source_id = created["source"]["id"]

    resp = client.post(f"/api/v1/sources/{source_id}/disconnect")
    assert resp.status_code == 200
    assert resp.json()["connection_state"] == "disconnected"
    # The source row remains listed (data preserved), just disconnected.
    listing = client.get("/api/v1/sources").json()
    assert [s["id"] for s in listing] == [source_id]


@pytest.mark.req("FRG-SRC-003")
def test_sync_now_on_disconnected_conflicts(client, tmp_path):
    _install_factory(
        client.app, tmp_path, order_handler(list_body=fixture_bytes("order_list.json"))
    )
    created = client.post("/api/v1/sources", json=_connect_body()).json()
    source_id = created["source"]["id"]
    client.post(f"/api/v1/sources/{source_id}/disconnect")

    resp = client.post(f"/api/v1/sources/{source_id}/sync")
    assert resp.status_code == 409


@pytest.mark.req("FRG-SRC-003")
def test_sync_now_enqueues_on_connected(client, tmp_path, monkeypatch):
    handler = order_handler(
        list_body=fixture_bytes("order_list.json"),
        order_bodies={"default": fixture_bytes("order_comics.json")},
    )
    factory = _install_factory(client.app, tmp_path, handler)
    # If the worker picks the job up, keep it on the mock transport (no network).
    monkeypatch.setattr(
        "foragerr.sources.commands.make_humble_factory", lambda settings: factory
    )
    created = client.post("/api/v1/sources", json=_connect_body()).json()
    source_id = created["source"]["id"]

    resp = client.post(f"/api/v1/sources/{source_id}/sync")
    assert resp.status_code == 202
    assert "command_id" in resp.json()


def resp_text(payload) -> str:
    import json

    return json.dumps(payload)
