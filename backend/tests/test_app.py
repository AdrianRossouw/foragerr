"""App factory behavior: independence, /api/v1 mount, lifespan hook order,
fail-fast startup exit (FRG-NFR-009).

Mostly untagged by design: the API-skeleton requirement tests land with the
api work area; these guard the shared factory contract the areas rely on.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from foragerr.app import create_app
from foragerr.config import CONFIG_FILENAME, Settings


def make_settings(tmp_path, name: str) -> Settings:
    path = tmp_path / name
    path.mkdir()
    return Settings(config_dir=path)


def test_two_create_app_calls_yield_independent_apps(tmp_path):
    app_a = create_app(make_settings(tmp_path, "a"))
    app_b = create_app(make_settings(tmp_path, "b"))

    assert app_a is not app_b
    assert app_a.state.settings is not app_b.state.settings
    baseline = list(app_b.state.startup_hooks)
    app_a.state.startup_hooks.append(object())
    assert app_b.state.startup_hooks == baseline  # no shared mutable state


def test_openapi_served_under_api_v1(tmp_path):
    app = create_app(make_settings(tmp_path, "cfg"))
    with TestClient(app) as client:
        response = client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "foragerr"


def test_lifespan_runs_startup_hooks_in_order_and_shutdown_reversed(tmp_path):
    app = create_app(make_settings(tmp_path, "cfg"))
    calls: list[str] = []

    def add(tag: str):
        async def _startup(app_):
            calls.append(f"up:{tag}")

        async def _shutdown(app_):
            calls.append(f"down:{tag}")

        app.state.startup_hooks.append(_startup)
        app.state.shutdown_hooks.append(_shutdown)

    add("db")
    add("sched")
    with TestClient(app):
        pass
    assert calls == ["up:db", "up:sched", "down:sched", "down:db"]


@pytest.mark.req("FRG-NFR-009")
def test_startup_with_invalid_config_exits_non_zero(config_dir, capsys):
    (config_dir / CONFIG_FILENAME).write_text('port: "nope"\n', encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        create_app()
    assert excinfo.value.code not in (0, None)
    assert "port" in capsys.readouterr().err  # operator sees the field name
