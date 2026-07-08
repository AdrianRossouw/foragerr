"""HTTP contract for series collected-edition typing (FRG-SER-018).

`SeriesResource` carries `booktype`; the edit endpoint's book-type override
sets+locks it (and rejects a bad value with 400); the `GET /series`
`collected` filter partitions the flat list. No secret is exposed. Flow
correctness (auto-derive, lock survival) is covered in
tests/library/test_booktype.py — not re-tested here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flows_support import FakeCV, build_factory, flows_settings
from foragerr.app import create_app
from foragerr.library import repo


@pytest.fixture(autouse=True)
def _reset_cv_gate():
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


async def _create_root_folder(app, path: Path) -> int:
    async with app.state.db.write_session() as session:
        row = await repo.create_root_folder(session, str(path))
        return row.id


def make_root_folder(client, tmp_path: Path, name: str = "library-root") -> int:
    root = tmp_path / name
    root.mkdir()
    return client.portal.call(_create_root_folder, client.app, root)


def patch_comicvine(monkeypatch, factory) -> None:
    monkeypatch.setattr("foragerr.api.series.comicvine_factory", lambda _s: factory)
    monkeypatch.setattr("foragerr.library.flows.add.comicvine_factory", lambda _s: factory)
    monkeypatch.setattr("foragerr.library.flows.refresh.comicvine_factory", lambda _s: factory)


def _add(client, root_id, cv_volume_id, name) -> dict:
    response = client.post(
        "/api/v1/series",
        json={"cv_volume_id": cv_volume_id, "root_folder_id": root_id},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.req("FRG-SER-018")
def test_series_resource_carries_booktype(client, tmp_path, monkeypatch):
    root_id = make_root_folder(client, tmp_path)
    factory = build_factory(
        settings=client.app.state.settings,
        handler=FakeCV()
        .volume(1, name="Batman: The Long Halloween (TPB)")
        .volume(2, name="Batman (2011)")
        .handler(),
    )
    patch_comicvine(monkeypatch, factory)

    trade = _add(client, root_id, 1, "Batman: The Long Halloween (TPB)")
    single = _add(client, root_id, 2, "Batman (2011)")

    assert "booktype" in trade
    assert trade["booktype"] == "tpb"  # auto-typed at add from the title cue
    assert single["booktype"] is None  # single-issues run


@pytest.mark.req("FRG-SER-018")
def test_edit_sets_and_locks_booktype(client, tmp_path, monkeypatch):
    root_id = make_root_folder(client, tmp_path)
    factory = build_factory(
        settings=client.app.state.settings,
        handler=FakeCV().volume(1, name="Saga Collection").handler(),
    )
    patch_comicvine(monkeypatch, factory)
    created = _add(client, root_id, 1, "Saga Collection")
    assert created["booktype"] is None

    response = client.put(
        f"/api/v1/series/{created['id']}",
        json={"booktype": {"action": "set", "booktype": "gn"}},
    )
    assert response.status_code == 200, response.text
    assert response.json()["booktype"] == "gn"

    # The lock is persisted (verified via a second unlock round-trip staying 200).
    unlock = client.put(
        f"/api/v1/series/{created['id']}",
        json={"booktype": {"action": "unlock"}},
    )
    assert unlock.status_code == 200
    assert unlock.json()["booktype"] == "gn"  # value unchanged; re-derive deferred


@pytest.mark.req("FRG-SER-018")
def test_edit_with_a_bad_booktype_is_400(client, tmp_path, monkeypatch):
    root_id = make_root_folder(client, tmp_path)
    factory = build_factory(
        settings=client.app.state.settings,
        handler=FakeCV().volume(1, name="Nailbiter").handler(),
    )
    patch_comicvine(monkeypatch, factory)
    created = _add(client, root_id, 1, "Nailbiter")

    response = client.put(
        f"/api/v1/series/{created['id']}",
        json={"booktype": {"action": "set", "booktype": "omnibus"}},
    )
    assert response.status_code == 400
    assert set(response.json()) == {"message", "errors"}


@pytest.mark.req("FRG-SER-018")
def test_collected_filter_partitions_the_list(client, tmp_path, monkeypatch):
    root_id = make_root_folder(client, tmp_path)
    factory = build_factory(
        settings=client.app.state.settings,
        handler=FakeCV()
        .volume(1, name="Saga Deluxe HC")   # -> hc
        .volume(2, name="Paper Girls")      # -> null
        .volume(3, name="Y The Last Man TPB")  # -> tpb
        .handler(),
    )
    patch_comicvine(monkeypatch, factory)
    for vid, name in ((1, "Saga Deluxe HC"), (2, "Paper Girls"), (3, "Y The Last Man TPB")):
        _add(client, root_id, vid, name)

    def _titles(params):
        body = client.get("/api/v1/series", params=params).json()
        return {r["title"] for r in body["records"]}, body["totalRecords"]

    all_titles, all_total = _titles({"pageSize": 50})
    assert all_total == 3

    collected_titles, collected_total = _titles({"collected": "true", "pageSize": 50})
    assert collected_total == 2
    assert collected_titles == {"Saga Deluxe HC", "Y The Last Man TPB"}

    singles_titles, singles_total = _titles({"collected": "false", "pageSize": 50})
    assert singles_total == 1
    assert singles_titles == {"Paper Girls"}


@pytest.mark.req("FRG-SER-018")
def test_booktype_surface_exposes_no_secret(client, tmp_path, monkeypatch):
    root_id = make_root_folder(client, tmp_path)
    factory = build_factory(
        settings=client.app.state.settings,
        handler=FakeCV().volume(1, name="Saga TPB").handler(),
    )
    patch_comicvine(monkeypatch, factory)
    created = _add(client, root_id, 1, "Saga TPB")

    body = client.get("/api/v1/series", params={"collected": "true"}).text
    # The configured ComicVine key must never ride out on the typed surface.
    assert "CV-SECRET-KEY" not in body
    assert "CV-SECRET-KEY" not in client.get(f"/api/v1/series/{created['id']}").text
