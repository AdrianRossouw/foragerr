"""Static SPA mount contract (FRG-DEP-001).

``register_spa`` serves the built React bundle at ``/`` from a single container,
without ever shadowing the API / OPDS / health routes and with history-API
fallback so client-side routes render the shell on a hard refresh. Absent a
build, it is a no-op and the API-only app is unchanged.

These exercise the mount contract directly (a tiny fixture dist tree), not a real
vite build — that is covered end-to-end by the Docker image tests.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from foragerr.app import create_app
from foragerr.config import Settings
from foragerr.spa import register_spa, resolve_static_dir


def _settings(tmp_path, name: str = "cfg") -> Settings:
    path = tmp_path / name
    path.mkdir()
    return Settings(config_dir=path)


def _fake_dist(tmp_path) -> "object":
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><div id=root>SPA</div>", "utf-8")
    (dist / "assets" / "app.js").write_text("console.log('spa')", "utf-8")
    return dist


@pytest.mark.req("FRG-DEP-001")
def test_register_spa_noop_without_bundle(tmp_path):
    """No dist dir → no-op; create_app stays importable without a frontend build."""
    app = FastAPI()
    assert register_spa(app, tmp_path / "does-not-exist") is False
    assert not any(getattr(r, "name", None) == "spa" for r in app.routes)


@pytest.mark.req("FRG-DEP-001")
def test_spa_serves_index_and_assets(tmp_path):
    app = FastAPI()
    assert register_spa(app, _fake_dist(tmp_path)) is True
    with TestClient(app) as client:
        root = client.get("/")
        asset = client.get("/assets/app.js")
    assert root.status_code == 200
    assert "SPA" in root.text
    assert asset.status_code == 200
    assert "console.log" in asset.text


@pytest.mark.req("FRG-DEP-001")
def test_spa_history_fallback_for_client_routes(tmp_path):
    """A deep link with no file on disk renders the SPA shell (history fallback),
    but a missing *asset* (path with a suffix) still 404s."""
    app = FastAPI()
    register_spa(app, _fake_dist(tmp_path))
    with TestClient(app) as client:
        deep = client.get("/series/5")
        missing_asset = client.get("/assets/gone.js")
    assert deep.status_code == 200
    assert "SPA" in deep.text
    assert missing_asset.status_code == 404


@pytest.mark.req("FRG-DEP-001")
def test_spa_never_shadows_api_health_or_opds(tmp_path):
    """Mounted on the real app, the SPA must not intercept API / OPDS / health."""
    app = create_app(_settings(tmp_path))
    # Mount a fake bundle on top of the already-built app (idempotent, additive).
    assert register_spa(app, _fake_dist(tmp_path)) is True
    with TestClient(app) as client:
        health = client.get("/health")
        openapi = client.get("/api/v1/openapi.json")
        opds = client.get("/opds")
        spa = client.get("/some/client/route")
    assert health.status_code in (200, 503)
    assert health.json()["status"] in ("up", "down")  # real health JSON, not the shell
    assert openapi.json()["info"]["title"] == "foragerr"
    assert opds.status_code == 200 and "xml" in opds.headers["content-type"]
    assert "SPA" in spa.text  # everything unclaimed falls through to the shell


@pytest.mark.req("FRG-DEP-001")
def test_resolve_static_dir_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("FORAGERR_STATIC_DIR", str(tmp_path / "custom"))
    assert resolve_static_dir() == tmp_path / "custom"
