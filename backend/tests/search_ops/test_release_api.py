"""Interactive-search release endpoint HTTP contract (FRG-API-008 / FRG-SRCH-014).

Drives the real wired app end-to-end: ``GET /api/v1/release?issueId=`` runs a
live search (over a stub Newznab feed injected via ``app.state.http_factory``)
and returns every decision comparator-sorted with cache keys; ``POST`` grabs
from the ~30 min cache or returns a deterministic 404-class "search again"
error.
"""

from __future__ import annotations

import datetime as dt
from functools import partial
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from foragerr.app import create_app
from foragerr.indexers.models import ReleaseCacheRow
from http_support import make_settings
from indexers_support import make_factory  # noqa: F401
from .support import feed_handler, make_indexer, make_issue, make_series


@pytest.fixture(autouse=True)
def _no_rate_gate(monkeypatch):
    """Neutralize the per-indexer 2 s spacing gate — the release API path uses
    the production ``DEFAULT_MIN_INTERVAL``, and these transport-stubbed tests
    have no reason to wait it out."""
    async def _immediate(indexer_id: int, min_interval: float = 0.0) -> None:
        return

    monkeypatch.setattr("foragerr.indexers.ratelimit.acquire", _immediate)


@pytest.fixture
def settings(tmp_path: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    return make_settings(cfg)


@pytest.fixture
def client(settings):
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


async def _setup(db, format_profile_id_getter):
    from .support import profile_id

    pid = await profile_id(db)
    root = db.db_path.parent / "root"
    root.mkdir(exist_ok=True)
    from foragerr.library import repo

    async with db.write_session() as session:
        rf = await repo.create_root_folder(session, str(root))
        root_folder_id = rf.id
    series_id = await make_series(
        db, format_profile_id=pid, root_folder_id=root_folder_id
    )
    issue_id = await make_issue(db, series_id=series_id, issue_number="7")
    indexer_id = await make_indexer(db)
    return series_id, issue_id, indexer_id


def _inject_feed(client, tmp_path, handler):
    factory, _ = make_factory(tmp_path, handler)
    client.app.state.http_factory = factory


@pytest.mark.req("FRG-API-008")
@pytest.mark.req("FRG-SRCH-014")
def test_get_release_returns_all_decisions_sorted_with_cache_keys(
    client, tmp_path
):
    db = client.app.state.db
    series_id, issue_id, indexer_id = client.portal.call(partial(_setup, db, None))
    # One approved (correct series) + one rejected (wrong series) release.
    _inject_feed(
        client, tmp_path, feed_handler("Saga 007 (2012)", "Batman 007 (2012)")
    )

    resp = client.get("/api/v1/release", params={"issueId": issue_id})
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 2
    # Comparator order: the approved release sorts first.
    assert rows[0]["approved"] is True
    assert rows[0]["rejections"] == []
    # An unknown-format-but-titled release is approved pre-download (3.5 note).
    assert rows[0]["format"] is None
    # The rejected wrong-series release still appears, with a visible reason.
    assert rows[1]["approved"] is False
    assert rows[1]["rejections"]
    # Every row carries its indexerId+guid cache key.
    for row in rows:
        assert row["indexer_id"] == indexer_id
        assert row["guid"]


@pytest.mark.req("FRG-API-008")
def test_post_release_cache_hit_enqueues_grab_command(client, tmp_path):
    db = client.app.state.db
    series_id, issue_id, indexer_id = client.portal.call(partial(_setup, db, None))
    _inject_feed(client, tmp_path, feed_handler("Saga 007 (2012)"))

    rows = client.get("/api/v1/release", params={"issueId": issue_id}).json()
    approved = next(r for r in rows if r["approved"])

    resp = client.post(
        "/api/v1/release",
        json={"indexer_id": approved["indexer_id"], "guid": approved["guid"]},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "grab-release"
    assert body["payload"]["guid"] == approved["guid"]
    assert body["payload"]["issue_id"] == issue_id


@pytest.mark.req("FRG-API-008")
def test_post_release_cache_miss_is_a_uniform_404(client, tmp_path):
    db = client.app.state.db
    series_id, issue_id, indexer_id = client.portal.call(partial(_setup, db, None))

    resp = client.post(
        "/api/v1/release", json={"indexer_id": indexer_id, "guid": "never-cached"}
    )
    assert resp.status_code == 404
    body = resp.json()
    assert set(body) == {"message", "errors"}  # uniform error shape
    assert "search" in body["message"].lower()


@pytest.mark.req("FRG-SRCH-014")
def test_post_release_after_expiry_returns_404_never_researches(client, tmp_path):
    db = client.app.state.db
    series_id, issue_id, indexer_id = client.portal.call(partial(_setup, db, None))
    _inject_feed(client, tmp_path, feed_handler("Saga 007 (2012)"))

    rows = client.get("/api/v1/release", params={"issueId": issue_id}).json()
    approved = next(r for r in rows if r["approved"])

    # Force the cached entry to be expired.
    async def _expire(db):
        past = dt.datetime(2000, 1, 1)
        async with db.write_session() as session:
            await session.execute(update(ReleaseCacheRow).values(expires_at=past))

    client.portal.call(partial(_expire, db))

    resp = client.post(
        "/api/v1/release",
        json={"indexer_id": approved["indexer_id"], "guid": approved["guid"]},
    )
    assert resp.status_code == 404
    assert "search" in resp.json()["message"].lower()


@pytest.mark.req("FRG-API-008")
def test_get_release_unknown_issue_is_404(client):
    resp = client.get("/api/v1/release", params={"issueId": 999999})
    assert resp.status_code == 404
    assert set(resp.json()) == {"message", "errors"}
