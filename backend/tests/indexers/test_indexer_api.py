"""Indexer schema + test HTTP endpoints (FRG-IDX-003, FRG-API-009)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from foragerr.app import create_app
from indexers_support import IDX_BASE, caps_doc, make_factory
from http_support import make_settings


@pytest.fixture
def settings(tmp_path: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    return make_settings(cfg)


def _client(settings, handler) -> TestClient:
    app = create_app(settings)
    factory, _ = make_factory(settings.config_dir, handler)
    app.state.http_factory = factory  # test-injection seam
    return TestClient(app)


def _test_body(**settings_overrides):
    body_settings = {"base_url": IDX_BASE, "api_key": "idx-fake-key-0000"}
    body_settings.update(settings_overrides)
    return {"implementation": "newznab", "settings": body_settings}


@pytest.mark.req("FRG-API-009")
@pytest.mark.req("FRG-IDX-003")
def test_schema_endpoint_returns_renderable_field_metadata(settings):
    with _client(settings, lambda r: httpx.Response(200)) as client:
        resp = client.get("/api/v1/indexer/schema")
    assert resp.status_code == 200
    body = resp.json()
    newznab = next(impl for impl in body if impl["implementation"] == "newznab")
    names = [f["name"] for f in newznab["fields"]]
    assert names == ["base_url", "api_key", "categories", "additional_parameters"]
    for f in newznab["fields"]:
        assert set(f) == {
            "order", "name", "type", "label", "help", "required",
            "secret", "advanced", "selectOptions",
        }
    orders = [f["order"] for f in newznab["fields"]]
    assert orders == sorted(orders)  # stable declared order


@pytest.mark.req("FRG-API-009")
def test_secret_fields_are_write_only_and_never_echoed(settings):
    with _client(settings, lambda r: httpx.Response(200)) as client:
        resp = client.get("/api/v1/indexer/schema")
    api_key = next(
        f
        for impl in resp.json()
        for f in impl["fields"]
        if f["name"] == "api_key"
    )
    assert api_key["secret"] is True
    assert "value" not in api_key  # no value surfaced anywhere
    assert "idx-fake-key" not in resp.text  # no secret material in the schema


@pytest.mark.req("FRG-IDX-003")
@pytest.mark.req("FRG-API-009")
def test_test_endpoint_runs_live_caps_probe_and_reports_success(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("t") == "caps"
        return httpx.Response(200, content=caps_doc())

    with _client(settings, handler) as client:
        resp = client.post("/api/v1/indexer/test", json=_test_body())
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["categories"]["7030"] == "Comics"
    assert body["degraded"] is False


@pytest.mark.req("FRG-IDX-003")
@pytest.mark.req("FRG-API-009")
def test_test_endpoint_maps_wrong_key_to_field_precise_auth_failure(settings):
    with _client(settings, lambda r: httpx.Response(401)) as client:
        resp = client.post("/api/v1/indexer/test", json=_test_body())
    assert resp.status_code == 400
    body = resp.json()
    assert body["errors"][0]["field"] == "api_key"  # field-precise, not generic


@pytest.mark.req("FRG-IDX-001")
@pytest.mark.req("FRG-API-009")
def test_test_endpoint_rejects_invalid_settings_with_field_errors(settings):
    # Missing base_url — validation fails before any probe; nothing persisted.
    with _client(settings, lambda r: httpx.Response(200)) as client:
        resp = client.post(
            "/api/v1/indexer/test",
            json={"implementation": "newznab", "settings": {"api_key": "k"}},
        )
    assert resp.status_code == 400
    assert resp.json()["errors"][0]["field"] == "settings.base_url"


@pytest.mark.req("FRG-API-009")
def test_test_endpoint_rejects_unknown_implementation(settings):
    with _client(settings, lambda r: httpx.Response(200)) as client:
        resp = client.post(
            "/api/v1/indexer/test",
            json={"implementation": "torznab", "settings": {}},
        )
    assert resp.status_code == 400
    assert resp.json()["errors"][0]["field"] == "implementation"
