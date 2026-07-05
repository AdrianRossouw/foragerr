"""``GET /api/v1/system/status`` + startup log line: version/build metadata,
degrading gracefully outside a built artifact (FRG-DEP-010)."""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from foragerr.app import create_app
from foragerr.config import Settings


@pytest.fixture
def app(tmp_path):
    path = tmp_path / "cfg"
    path.mkdir()
    return create_app(Settings(config_dir=path))


@pytest.mark.req("FRG-DEP-010")
def test_system_status_reports_version_commit_build_date(app, monkeypatch):
    monkeypatch.setenv("FORAGERR_BUILD_COMMIT", "abc1234")
    monkeypatch.setenv("FORAGERR_BUILD_DATE", "2026-07-04")
    with TestClient(app) as client:
        response = client.get("/api/v1/system/status")
    assert response.status_code == 200
    body = response.json()
    assert body["commit"] == "abc1234"
    assert body["build_date"] == "2026-07-04"
    assert body["version"]  # non-empty; exact value is the installed package version


@pytest.mark.req("FRG-DEP-010")
def test_metadata_falls_back_to_placeholders_without_env(app, monkeypatch):
    monkeypatch.delenv("FORAGERR_BUILD_COMMIT", raising=False)
    monkeypatch.delenv("FORAGERR_BUILD_DATE", raising=False)
    with TestClient(app) as client:
        response = client.get("/api/v1/system/status")
    body = response.json()
    assert body["commit"] == "unknown"
    assert body["build_date"] == "unknown"


@pytest.mark.req("FRG-DEP-010")
def test_version_falls_back_to_placeholder_outside_a_built_artifact(monkeypatch):
    """Package metadata absent (e.g. a raw source checkout with no install)
    must degrade to a well-defined placeholder, never error or omit the
    field."""
    from foragerr.db import migrations as mig

    def _raise(_name: str):
        raise ModuleNotFoundError("no package metadata")

    monkeypatch.setattr("importlib.metadata.version", _raise)
    assert mig.app_version() == "0+unknown"


@pytest.mark.req("FRG-DEP-010")
def test_startup_log_line_matches_the_api_reported_values(app, caplog, monkeypatch):
    monkeypatch.setenv("FORAGERR_BUILD_COMMIT", "deadbeef")
    monkeypatch.setenv("FORAGERR_BUILD_DATE", "2026-01-01")
    with caplog.at_level(logging.INFO, logger="foragerr.system"):
        with TestClient(app) as client:
            response = client.get("/api/v1/system/status")
    body = response.json()
    startup_lines = [r.message for r in caplog.records if "foragerr starting" in r.message]
    assert startup_lines, "expected an early startup log line carrying version info"
    line = startup_lines[0]
    assert body["version"] in line
    assert body["commit"] in line
    assert body["build_date"] in line


@pytest.mark.req("FRG-DEP-010")
def test_version_line_is_logged_before_any_area_startup(app, caplog):
    """The version line is a startup contract: it must appear BEFORE the db /
    commands areas log their own startup, not last (FRG-DEP-010)."""
    with caplog.at_level(logging.INFO):
        with TestClient(app):
            pass

    records = [(r.name, r.getMessage()) for r in caplog.records]
    version_idx = next(
        i for i, (_name, msg) in enumerate(records) if "foragerr starting" in msg
    )
    area_idx = next(
        (
            i
            for i, (name, _msg) in enumerate(records)
            if name.startswith("foragerr.db") or name.startswith("foragerr.commands")
        ),
        None,
    )
    assert area_idx is not None, "expected a db/commands startup record"
    assert version_idx < area_idx  # version emitted before any area startup
