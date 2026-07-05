"""FRG-DL-002 — download-client provider table shape + schema/test endpoints."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from foragerr.app import create_app
from foragerr.db import DB_FILENAME, prepare_database
from downloads_support import SAB_BASE, SabFixture, make_sab_factory
from http_support import make_settings


@pytest.fixture
def settings(tmp_path: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    return make_settings(cfg)


def _client(settings, fixture: SabFixture) -> TestClient:
    app = create_app(settings)
    factory, _ = make_sab_factory(settings.config_dir, fixture)
    app.state.http_factory = factory  # test-injection seam (mirrors indexers)
    return TestClient(app)


def _test_body(**overrides):
    body_settings = {"base_url": SAB_BASE, "api_key": "sab-fake-key"}
    body_settings.update(overrides)
    return {"implementation": "sabnzbd", "settings": body_settings}


@pytest.mark.req("FRG-DL-001")
@pytest.mark.req("FRG-DL-002")
def test_migration_creates_all_six_change5_tables(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    prepare_database(cfg)
    with sqlite3.connect(cfg / DB_FILENAME) as conn:
        tables = {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert {
        "download_clients",
        "grab_history",
        "tracked_downloads",
        "blocklist",
        "remote_path_mappings",
        "ddl_queue",
    } <= tables


@pytest.mark.req("FRG-DL-002")
def test_schema_endpoint_mirrors_the_indexer_contract(settings):
    with _client(settings, SabFixture()) as client:
        resp = client.get("/api/v1/downloadclient/schema")
    assert resp.status_code == 200
    body = resp.json()
    sab = next(impl for impl in body if impl["implementation"] == "sabnzbd")
    assert sab["protocol"] == "usenet"
    names = [f["name"] for f in sab["fields"]]
    assert names == ["base_url", "api_key", "category", "priority"]
    for field in sab["fields"]:
        assert set(field) == {
            "order", "name", "type", "label", "help", "required",
            "secret", "advanced", "selectOptions",
        }
    # ddl is a first-class provider row from day one (FRG-DDL-001).
    assert any(impl["protocol"] == "ddl" for impl in body)


@pytest.mark.req("FRG-DL-002")
def test_secret_api_key_is_write_only_in_schema(settings):
    with _client(settings, SabFixture()) as client:
        resp = client.get("/api/v1/downloadclient/schema")
    api_key = next(
        f for impl in resp.json() for f in impl["fields"] if f["name"] == "api_key"
    )
    assert api_key["secret"] is True
    assert "value" not in api_key


@pytest.mark.req("FRG-DL-002")
def test_test_endpoint_runs_version_and_config_probe(settings):
    with _client(settings, SabFixture()) as client:
        resp = client.post("/api/v1/downloadclient/test", json=_test_body())
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["version"] == "4.3.2"


@pytest.mark.req("FRG-DL-002")
def test_test_endpoint_unreachable_sab_is_field_precise_failure(settings):
    fixture = SabFixture()
    fixture.sab_status = 503
    with _client(settings, fixture) as client:
        resp = client.post("/api/v1/downloadclient/test", json=_test_body())
    assert resp.status_code == 400
    assert resp.json()["errors"][0]["field"] == "base_url"


@pytest.mark.req("FRG-DL-002")
def test_test_endpoint_rejects_invalid_settings_with_field_errors(settings):
    with _client(settings, SabFixture()) as client:
        resp = client.post(
            "/api/v1/downloadclient/test",
            json={"implementation": "sabnzbd", "settings": {"api_key": "k"}},
        )
    assert resp.status_code == 400
    assert resp.json()["errors"][0]["field"] == "settings.base_url"


@pytest.mark.req("FRG-DL-002")
def test_test_endpoint_rejects_unknown_implementation(settings):
    with _client(settings, SabFixture()) as client:
        resp = client.post(
            "/api/v1/downloadclient/test",
            json={"implementation": "nzbget", "settings": {}},
        )
    assert resp.status_code == 400
    assert resp.json()["errors"][0]["field"] == "implementation"
