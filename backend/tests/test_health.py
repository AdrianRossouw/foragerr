"""``GET /health``: root-level, credential-free liveness/readiness
(FRG-DEP-007) — slimmed to status + failing names in M10 (FRG-SEC-008), with
the component detail behind auth on ``/api/v1/system/health/components``."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from foragerr.app import create_app
from foragerr.config import Settings

#: Internal detail that must NEVER appear in the unauthenticated probe body.
_DISCLOSURE_MARKERS = ("path", "revision", "current", "head", "error", "tasks", "components")


@pytest.fixture
def app(tmp_path):
    path = tmp_path / "cfg"
    path.mkdir()
    return create_app(Settings(config_dir=path))


@pytest.mark.req("FRG-DEP-007")
@pytest.mark.req("FRG-API-014")
def test_health_is_root_level_and_distinct_from_api_v1_health(app):
    """The root liveness probe stays at ``/health``; ``GET /api/v1/health``
    is a DIFFERENT resource (FRG-API-014: the actionable health-warnings
    list). The two shapes prove they are distinct: the root probe is a
    minimal status object, ``/api/v1/health`` is a warnings array."""
    with TestClient(app) as client:
        root_response = client.get("/health")
        api_response = client.get("/api/v1/health")
    assert root_response.status_code == 200
    assert root_response.json() == {"status": "up"}

    assert api_response.status_code == 200
    assert isinstance(api_response.json(), list)


@pytest.mark.req("FRG-DEP-007")
@pytest.mark.req("FRG-SEC-008")
def test_healthy_probe_is_minimal_and_credential_free(app):
    """A bare unauthenticated probe gets 200 with overall status ONLY — no
    component detail, filesystem path, migration revision, or version."""
    with TestClient(app) as client:
        client.headers.pop("X-Api-Key", None)  # genuinely unauthenticated
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "up"}
    for marker in _DISCLOSURE_MARKERS:
        assert marker not in body


@pytest.mark.req("FRG-DEP-007")
@pytest.mark.req("FRG-SEC-008")
def test_unhealthy_database_names_component_without_detail(app):
    """503 identifies the failing component by NAME only — the error text
    (which may embed paths) never reaches the unauthenticated body."""
    with TestClient(app) as client:
        client.headers.pop("X-Api-Key", None)

        async def _down():
            return {"status": "down", "error": "simulated outage /secret/db/path"}

        app.state.db.health = _down
        response = client.get("/health")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "down"
    assert body["failing"] == ["database"]
    assert "simulated outage" not in response.text
    assert "/secret/db/path" not in response.text


@pytest.mark.req("FRG-DEP-007")
def test_unhealthy_scheduler_flips_endpoint_non_2xx_and_names_it(app):
    with TestClient(app) as client:

        async def _broken():
            raise RuntimeError("scheduler loop is stopped")

        app.state.scheduler.status = _broken
        response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["failing"] == ["scheduler"]


@pytest.mark.req("FRG-DEP-007")
def test_unhealthy_migration_state_flips_endpoint_non_2xx(app, monkeypatch):
    with TestClient(app) as client:
        monkeypatch.setattr(
            "foragerr.api.health.current_revision", lambda _path: "some-unknown-rev"
        )
        response = client.get("/health")
    assert response.status_code == 503
    assert "migrations" in response.json()["failing"]
    assert "some-unknown-rev" not in response.text  # revision stays server-side


@pytest.mark.req("FRG-DEP-007")
def test_health_requires_no_credentials(app):
    with TestClient(app) as client:
        client.headers.pop("X-Api-Key", None)
        response = client.get("/health")  # no auth headers/cookies/api key at all
    assert response.status_code == 200


@pytest.mark.req("FRG-DEP-007")
@pytest.mark.req("FRG-SEC-008")
def test_component_detail_lives_behind_the_perimeter(app):
    """The detail formerly on ``/health`` is served authenticated on
    ``/api/v1/system/health/components`` — and refused without credentials."""
    with TestClient(app) as client:
        authed = client.get("/api/v1/system/health/components")
        client.headers.pop("X-Api-Key", None)
        bare = client.get("/api/v1/system/health/components")

    assert authed.status_code == 200
    body = authed.json()
    assert body["status"] == "up"
    for component in ("database", "workers", "scheduler", "migrations"):
        assert component in body["components"]
        assert body["components"][component]["status"] == "up"

    assert bare.status_code == 401


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
    assert response.json() == {"status": "up"}
