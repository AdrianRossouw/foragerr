"""FRG-API-005 (command endpoint HTTP contract) exercised against a REAL
production command name (``refresh-series``, registered by the library flows
package) rather than the foundation's synthetic ``noop`` — proves the
transport works for the commands this change actually adds, not just the
backbone's own smoke-test command.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from flows_support import FakeCV, build_factory, flows_settings
from foragerr.app import create_app
from foragerr.library import repo
from foragerr.quality.models import DEFAULT_PROFILE_NAME, FormatProfileRow


@pytest.fixture(autouse=True)
def _reset_cv_gate():
    """Isolate the process-global ComicVine rate gate around every test in
    this file — see the identical fixture in test_series_api.py for why a
    flat backend/tests/ file needs its own copy of this convention."""
    from foragerr.metadata import ratelimit

    ratelimit.reset_gate()
    yield
    ratelimit.reset_gate()


@pytest.fixture
def settings(tmp_path: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    return flows_settings(cfg)


@pytest.fixture
def client(settings):
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


async def _seed_series(app, root_path: Path) -> int:
    async with app.state.db.write_session() as session:
        profile_id = await session.scalar(
            select(FormatProfileRow.id).where(FormatProfileRow.name == DEFAULT_PROFILE_NAME)
        )
        root = await repo.create_root_folder(session, str(root_path))
        series = await repo.create_series(
            session,
            cv_volume_id=42,
            title="Saga",
            root_folder_id=root.id,
            format_profile_id=profile_id,
            path=str(root_path / "Saga"),
        )
        return series.id


def make_series(client, tmp_path: Path) -> int:
    return client.portal.call(_seed_series, client.app, tmp_path / "root")


def patch_comicvine_for_refresh(monkeypatch, factory) -> None:
    """Patch ONLY the ``refresh-series`` command handler's ComicVine seam
    (this file never drives ``add_series`` or the `/series/lookup` router,
    so — unlike ``test_series_api.py``'s broader ``patch_comicvine`` helper
    of the same shape — patching the other two call sites is unnecessary
    here; the distinct name is deliberate to avoid the two helpers being
    mistaken for each other across files)."""
    monkeypatch.setattr(
        "foragerr.library.flows.refresh.comicvine_factory", lambda _settings: factory
    )


@pytest.mark.req("FRG-API-005")
def test_refresh_series_command_post_returns_201_trackable_resource(
    client, tmp_path, monkeypatch
):
    series_id = make_series(client, tmp_path)
    factory = build_factory(
        settings=client.app.state.settings,
        handler=FakeCV().volume(42, name="Saga").issues(42, []).handler(),
    )
    patch_comicvine_for_refresh(monkeypatch, factory)

    response = client.post(
        "/api/v1/command",
        json={"name": "refresh-series", "payload": {"series_id": series_id}},
    )
    assert response.status_code == 201
    body = response.json()
    assert isinstance(body["id"], int)
    assert body["name"] == "refresh-series"
    assert body["status"] in ("queued", "started", "completed")
    assert body["payload"] == {"series_id": series_id}


@pytest.mark.req("FRG-API-005")
def test_refresh_series_command_tracks_to_completed_via_get(
    client, tmp_path, monkeypatch
):
    series_id = make_series(client, tmp_path)
    factory = build_factory(
        settings=client.app.state.settings,
        handler=FakeCV().volume(42, name="Saga").issues(42, []).handler(),
    )
    patch_comicvine_for_refresh(monkeypatch, factory)

    created = client.post(
        "/api/v1/command",
        json={"name": "refresh-series", "payload": {"series_id": series_id}},
    ).json()

    deadline = time.monotonic() + 5.0
    body = None
    while time.monotonic() < deadline:
        body = client.get(f"/api/v1/command/{created['id']}").json()
        if body["status"] in ("completed", "failed"):
            break
        time.sleep(0.05)
    assert body is not None
    assert body["status"] == "completed"


@pytest.mark.req("FRG-API-005")
def test_resubmitting_refresh_series_while_queued_dedups_to_same_id(
    client, tmp_path, monkeypatch
):
    series_id = make_series(client, tmp_path)
    factory = build_factory(
        settings=client.app.state.settings,
        handler=FakeCV().volume(42, name="Saga").issues(42, []).handler(),
    )
    patch_comicvine_for_refresh(monkeypatch, factory)

    payload = {"series_id": series_id}
    first = client.post(
        "/api/v1/command", json={"name": "refresh-series", "payload": payload}
    )
    second = client.post(
        "/api/v1/command", json={"name": "refresh-series", "payload": payload}
    )
    assert first.status_code == 201
    assert second.status_code == 201
    if first.json()["status"] != "completed":
        assert second.json()["id"] == first.json()["id"]


@pytest.mark.req("FRG-API-005")
def test_unknown_command_name_is_400_no_command_queued(client):
    response = client.post("/api/v1/command", json={"name": "not-a-real-command"})
    assert response.status_code == 400
    body = response.json()
    assert set(body) == {"message", "errors"}

    # No command was queued for the rejected name (unrelated commands, e.g.
    # the scheduler's own startup housekeeping run, may legitimately exist).
    listing = client.get("/api/v1/command", params={"pageSize": 200}).json()
    names = {record["name"] for record in listing["records"]}
    assert "not-a-real-command" not in names
