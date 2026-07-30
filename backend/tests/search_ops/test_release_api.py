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
from .support import feed_handler, grab_rows, make_indexer, make_issue, make_series


@pytest.fixture(autouse=True)
def _no_rate_gate(monkeypatch):
    """Neutralize the per-indexer 2 s spacing gate — the release API path uses
    the production ``DEFAULT_MIN_INTERVAL``, and these transport-stubbed tests
    have no reason to wait it out."""
    async def _immediate(
        indexer_id: int, min_interval: float = 0.0, *, priority: bool = False
    ) -> None:
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
    body = resp.json()
    rows = body["releases"]
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
    # The quiet case: the one indexer searched, nothing timed out.
    assert body["indexers"] == [
        {
            "indexer_id": indexer_id,
            "name": "DogNZB",
            "outcome": "searched",
            "budget_seconds": None,
            "candidate_count": 2,
        }
    ]


@pytest.mark.req("FRG-API-008")
def test_post_release_cache_hit_enqueues_grab_command(client, tmp_path):
    db = client.app.state.db
    series_id, issue_id, indexer_id = client.portal.call(partial(_setup, db, None))
    _inject_feed(client, tmp_path, feed_handler("Saga 007 (2012)"))

    rows = client.get(
        "/api/v1/release", params={"issueId": issue_id}
    ).json()["releases"]
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
    # An approved grab is a plain interactive grab (not a forced override).
    assert body["triggered_by"] == "interactive"


@pytest.mark.req("FRG-API-008")
def test_post_release_rejected_is_refused_409_and_enqueues_nothing(client, tmp_path):
    """A cached release whose decision was NOT approved is refused without force,
    and NO grab command is enqueued (the server gate, not a client trick)."""
    db = client.app.state.db
    series_id, issue_id, indexer_id = client.portal.call(partial(_setup, db, None))
    # A wrong-series release is decided REJECTED and cached not-approved.
    _inject_feed(
        client, tmp_path, feed_handler("Saga 007 (2012)", "Batman 007 (2012)")
    )

    rows = client.get(
        "/api/v1/release", params={"issueId": issue_id}
    ).json()["releases"]
    rejected = next(r for r in rows if not r["approved"])

    resp = client.post(
        "/api/v1/release",
        json={"indexer_id": rejected["indexer_id"], "guid": rejected["guid"]},
    )
    assert resp.status_code == 409
    body = resp.json()
    assert set(body) == {"message", "errors"}  # uniform error shape
    assert "quality" in body["message"].lower()
    assert "force" in body["message"].lower()
    # The gate enqueued nothing.
    assert client.portal.call(partial(grab_rows, db)) == []


@pytest.mark.req("FRG-API-008")
def test_post_release_rejected_with_force_grabs_as_interactive_forced(client, tmp_path):
    """``force: true`` overrides the gate: the SAME grab hand-off is enqueued,
    recorded as ``triggered_by="interactive-forced"``."""
    db = client.app.state.db
    series_id, issue_id, indexer_id = client.portal.call(partial(_setup, db, None))
    _inject_feed(
        client, tmp_path, feed_handler("Saga 007 (2012)", "Batman 007 (2012)")
    )

    rows = client.get(
        "/api/v1/release", params={"issueId": issue_id}
    ).json()["releases"]
    rejected = next(r for r in rows if not r["approved"])

    resp = client.post(
        "/api/v1/release",
        json={
            "indexer_id": rejected["indexer_id"],
            "guid": rejected["guid"],
            "force": True,
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "grab-release"
    assert body["payload"]["guid"] == rejected["guid"]
    assert body["triggered_by"] == "interactive-forced"
    # Exactly one grab command, carrying the forced stamp on the persisted row.
    enqueued = client.portal.call(partial(grab_rows, db))
    assert [r.triggered_by for r in enqueued] == ["interactive-forced"]


@pytest.mark.req("FRG-API-008")
def test_post_release_null_approved_is_fail_safe_refused(client, tmp_path):
    """A cache row with NULL ``approved`` (a pre-0030 row) is treated as NOT
    approved: refused without force, fail-safe rather than fail-open."""
    db = client.app.state.db
    series_id, issue_id, indexer_id = client.portal.call(partial(_setup, db, None))
    _inject_feed(client, tmp_path, feed_handler("Saga 007 (2012)"))

    rows = client.get(
        "/api/v1/release", params={"issueId": issue_id}
    ).json()["releases"]
    approved = next(r for r in rows if r["approved"])

    # Simulate a pre-0030 cache row: null out the recorded verdict.
    async def _null_approved(db):
        async with db.write_session() as session:
            await session.execute(update(ReleaseCacheRow).values(approved=None))

    client.portal.call(partial(_null_approved, db))

    resp = client.post(
        "/api/v1/release",
        json={"indexer_id": approved["indexer_id"], "guid": approved["guid"]},
    )
    assert resp.status_code == 409
    assert "force" in resp.json()["message"].lower()
    assert client.portal.call(partial(grab_rows, db)) == []


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


@pytest.mark.req("FRG-API-008")
def test_post_release_cache_miss_is_404_even_with_force(client, tmp_path):
    """A cache miss is a 404 regardless of ``force`` — force overrides the
    approval gate, never the "search again" contract."""
    db = client.app.state.db
    series_id, issue_id, indexer_id = client.portal.call(partial(_setup, db, None))

    resp = client.post(
        "/api/v1/release",
        json={"indexer_id": indexer_id, "guid": "never-cached", "force": True},
    )
    assert resp.status_code == 404
    assert "search" in resp.json()["message"].lower()
    assert client.portal.call(partial(grab_rows, db)) == []


@pytest.mark.req("FRG-SRCH-014")
def test_post_release_after_expiry_returns_404_never_researches(client, tmp_path):
    db = client.app.state.db
    series_id, issue_id, indexer_id = client.portal.call(partial(_setup, db, None))
    _inject_feed(client, tmp_path, feed_handler("Saga 007 (2012)"))

    rows = client.get(
        "/api/v1/release", params={"issueId": issue_id}
    ).json()["releases"]
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


@pytest.mark.req("FRG-SER-022")
def test_post_release_is_refused_for_a_read_only_series_even_with_force(
    client, tmp_path
):
    """``force`` overrides the QUALITY rules only, never the read-only
    reference-library boundary (FRG-SER-022): a browse-only series has nowhere
    to download into. The root is flipped AFTER the search, which is also the
    real ordering hazard — a cache entry outlives the search that filled it, so
    the boundary is re-checked at grab time rather than trusted from cache."""
    from foragerr.library.models import RootFolderRow

    db = client.app.state.db
    _series_id, issue_id, _indexer_id = client.portal.call(partial(_setup, db, None))
    _inject_feed(client, tmp_path, feed_handler("Saga 007 (2012)"))
    approved = next(
        r
        for r in client.get(
            "/api/v1/release", params={"issueId": issue_id}
        ).json()["releases"]
        if r["approved"]
    )

    async def _mark_read_only(db):
        async with db.write_session() as session:
            await session.execute(update(RootFolderRow).values(read_only=True))

    client.portal.call(partial(_mark_read_only, db))

    resp = client.post(
        "/api/v1/release",
        json={
            "indexer_id": approved["indexer_id"],
            "guid": approved["guid"],
            "force": True,
        },
    )

    assert resp.status_code == 409
    body = resp.json()
    assert "read-only reference library" in body["message"]
    assert [e["field"] for e in body["errors"]] == ["read_only"]
    # The refusal is fail-closed: nothing was handed off to a downloader.
    assert client.portal.call(partial(grab_rows, db)) == []
