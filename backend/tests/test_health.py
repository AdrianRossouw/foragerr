"""``GET /health``: root-level, credential-free liveness/readiness
(FRG-DEP-007)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from foragerr.app import create_app
from foragerr.config import Settings


@pytest.fixture
def app(tmp_path):
    path = tmp_path / "cfg"
    path.mkdir()
    return create_app(Settings(config_dir=path))


@pytest.mark.req("FRG-DEP-007")
def test_health_is_root_level_not_under_api_v1(app):
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    # A second request under /api/v1 must NOT exist for the same resource.
    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 404


@pytest.mark.req("FRG-DEP-007")
def test_healthy_instance_returns_200_with_component_statuses(app):
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "up"
    for component in ("database", "workers", "scheduler", "migrations"):
        assert component in body["components"]
        assert body["components"][component]["status"] == "up"


@pytest.mark.req("FRG-DEP-007")
def test_health_requires_no_credentials(app):
    with TestClient(app) as client:
        response = client.get("/health")  # no auth headers/cookies/api key at all
    assert response.status_code == 200


@pytest.mark.req("FRG-DEP-007")
def test_unhealthy_database_flips_endpoint_non_2xx_and_names_it(app):
    with TestClient(app) as client:

        async def _down():
            return {"status": "down", "error": "simulated outage"}

        app.state.db.health = _down
        response = client.get("/health")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "down"
    assert body["components"]["database"]["status"] == "down"


@pytest.mark.req("FRG-DEP-007")
def test_unhealthy_scheduler_flips_endpoint_non_2xx_and_names_it(app):
    with TestClient(app) as client:

        async def _broken():
            raise RuntimeError("scheduler loop is stopped")

        app.state.scheduler.status = _broken
        response = client.get("/health")
    assert response.status_code == 503
    body = response.json()
    assert body["components"]["scheduler"]["status"] == "down"
    assert "database" in body["components"]  # other components still reported


@pytest.mark.req("FRG-DEP-007")
def test_unhealthy_migration_state_flips_endpoint_non_2xx(app, monkeypatch):
    with TestClient(app) as client:
        monkeypatch.setattr(
            "foragerr.api.health.current_revision", lambda _path: "some-unknown-rev"
        )
        response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["components"]["migrations"]["status"] == "down"


@pytest.mark.req("FRG-DEP-007")
def test_health_probe_does_no_synchronous_alembic_parse_per_request(app, monkeypatch):
    """The migration head is resolved ONCE at startup; a probe must not parse
    the Alembic script tree on the event loop. Poison the parser AFTER startup
    and the endpoint must still answer 200 from the cached head (FRG-DEP-007)."""
    from alembic.script import ScriptDirectory

    with TestClient(app) as client:
        assert app.state.migration_head is not None  # cached at startup

        def _boom(*_args, **_kwargs):
            raise AssertionError("Alembic parsed on the request path")

        monkeypatch.setattr(ScriptDirectory, "from_config", staticmethod(_boom))
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["components"]["migrations"]["status"] == "up"
