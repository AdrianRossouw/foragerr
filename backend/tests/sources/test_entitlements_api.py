"""Entitlement review HTTP surface (FRG-SRC-004): list/detail/actions/bulk.

Entitlements are populated by running the sync service directly against the
app's database (the queue-driven "Sync now" is covered in test_sources_api);
these tests exercise the review endpoints themselves.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from foragerr.app import create_app
from foragerr.library import repo as library_repo
from foragerr.quality.models import DEFAULT_PROFILE_NAME, FormatProfileRow
from foragerr.sources import ratelimit, repo
from foragerr.sources.registry import TYPE_HUMBLE
from foragerr.sources.service import run_sync
from foragerr.sources.settings import HumbleSettings
from http_support import make_settings
from sources_support import fixture_bytes, make_factory, order_handler

GAMEKEY = "aBcD1234synthetic"


@pytest.fixture(autouse=True)
def _reset_gates():
    ratelimit.reset_gates()
    yield
    ratelimit.reset_gates()


@pytest.fixture
def app_client(tmp_path: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    app = create_app(make_settings(cfg))
    with TestClient(app) as c:
        yield c


async def _populate(app) -> int:
    db = app.state.db
    source = await repo.create_source(
        db,
        source_type=TYPE_HUMBLE,
        name="Humble Bundle",
        settings=HumbleSettings(session_cookie="SYNTH-COOKIE"),
        connection_state="connected",
    )
    factory = make_factory(
        app.state.settings.config_dir,
        httpx.MockTransport(
            order_handler(
                list_body=b'[{"gamekey":"%s"}]' % GAMEKEY.encode(),
                order_bodies={GAMEKEY: fixture_bytes("order_comics.json")},
            )
        ),
    )
    await run_sync(db, factory, source, min_interval=0.0)
    return source.id


async def _first_comic_id(app, source_id: int) -> int:
    comics = await repo.list_entitlements(
        app.state.db, source_id, classification="comic", review_status="new"
    )
    return comics[0].id


@pytest.mark.req("FRG-SRC-004")
async def test_list_and_detail(app_client):
    app = app_client.app
    source_id = await _populate(app)

    comics = app_client.get(
        f"/api/v1/sources/{source_id}/entitlements?classification=comic"
    ).json()
    assert len(comics) == 3
    assert all(c["classification"] == "comic" for c in comics)
    # The cookie/md5 internals are not needed by the review UI shape, but the
    # review + download axes are present.
    assert {"review_status", "download_state"} <= set(comics[0])

    detail = app_client.get(
        f"/api/v1/sources/entitlements/{comics[0]['id']}"
    ).json()
    assert detail["id"] == comics[0]["id"]
    assert detail["fill_sets"] == []  # no matched series yet


@pytest.mark.req("FRG-SRC-004")
async def test_ignore_restore_roundtrip(app_client):
    app = app_client.app
    source_id = await _populate(app)
    eid = await _first_comic_id(app, source_id)

    ignored = app_client.post(f"/api/v1/sources/entitlements/{eid}/ignore").json()
    assert ignored["review_status"] == "ignored"

    restored = app_client.post(f"/api/v1/sources/entitlements/{eid}/restore").json()
    assert restored["review_status"] == "new"


@pytest.mark.req("FRG-SRC-004")
async def test_match_endpoint_links_series(app_client):
    app = app_client.app
    source_id = await _populate(app)
    eid = await _first_comic_id(app, source_id)

    async with app.state.db.read_session() as session:
        from sqlalchemy import select

        fp_id = (
            await session.execute(
                select(FormatProfileRow.id).where(
                    FormatProfileRow.name == DEFAULT_PROFILE_NAME
                )
            )
        ).scalar_one()
    root = Path(app.state.settings.config_dir) / "root"
    root.mkdir()
    async with app.state.db.write_session() as session:
        rf = await library_repo.create_root_folder(session, str(root))
        series = await library_repo.create_series(
            session,
            cv_volume_id=9001,
            title="Synthetic Hero",
            format_profile_id=fp_id,
            root_folder_id=rf.id,
            path=str(root / "Synthetic Hero"),
        )
        series_id = series.id

    resp = app_client.post(
        f"/api/v1/sources/entitlements/{eid}/match", json={"series_id": series_id}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["review_status"] == "matched"
    assert body["matched_series_id"] == series_id


@pytest.mark.req("FRG-SRC-004")
async def test_bulk_ignore_endpoint(app_client):
    app = app_client.app
    source_id = await _populate(app)
    comics = await repo.list_entitlements(app.state.db, source_id, classification="comic")
    ids = [c.id for c in comics]

    resp = app_client.post(
        "/api/v1/sources/entitlements/bulk",
        json={"action": "ignore", "entitlement_ids": ids},
    )
    assert resp.status_code == 200
    assert resp.json()["applied"] == len(ids)

    remaining = app_client.get(
        f"/api/v1/sources/{source_id}/entitlements?review_status=new&classification=comic"
    ).json()
    assert remaining == []


@pytest.mark.req("FRG-SRC-004")
async def test_bulk_match_requires_series_id(app_client):
    app = app_client.app
    source_id = await _populate(app)
    comics = await repo.list_entitlements(app.state.db, source_id, classification="comic")
    resp = app_client.post(
        "/api/v1/sources/entitlements/bulk",
        json={"action": "match", "entitlement_ids": [comics[0].id]},
    )
    assert resp.status_code == 422


@pytest.mark.req("FRG-SRC-004")
async def test_patch_auto_sync_flips_on_then_off_and_persists(app_client):
    """The auto-sync toggle ships OFF and is changeable post-connect via
    PATCH /sources/{id}: ON then OFF, each flip persisted (FRG-SRC-004)."""
    app = app_client.app
    source_id = await _populate(app)
    # Ships OFF.
    assert app_client.get("/api/v1/sources").json()[0]["auto_sync"] is False

    on = app_client.patch(f"/api/v1/sources/{source_id}", json={"auto_sync": True})
    assert on.status_code == 200
    assert on.json()["auto_sync"] is True
    assert app_client.get("/api/v1/sources").json()[0]["auto_sync"] is True

    off = app_client.patch(f"/api/v1/sources/{source_id}", json={"auto_sync": False})
    assert off.status_code == 200
    assert off.json()["auto_sync"] is False
    assert app_client.get("/api/v1/sources").json()[0]["auto_sync"] is False
    # The cookie is never echoed back on the manage response.
    assert "session_cookie" not in off.json()["settings"]


@pytest.mark.req("FRG-SRC-004")
async def test_patch_auto_sync_on_does_not_retroactively_accept(app_client):
    """Flipping auto-sync ON only persists the flag — it NEVER retroactively
    accepts existing `new` entitlements. Auto-accept fires exclusively on a
    subsequent sync's confident matches (FRG-SRC-004)."""
    app = app_client.app
    source_id = await _populate(app)
    before = await repo.list_entitlements(
        app.state.db, source_id, classification="comic", review_status="new"
    )
    assert before  # the fixture yields un-reviewed new comics

    resp = app_client.patch(f"/api/v1/sources/{source_id}", json={"auto_sync": True})
    assert resp.status_code == 200

    # Every previously-new comic is STILL new — nothing was accepted/matched.
    after_new = await repo.list_entitlements(
        app.state.db, source_id, classification="comic", review_status="new"
    )
    assert {e.id for e in after_new} == {e.id for e in before}
    after_matched = await repo.list_entitlements(
        app.state.db, source_id, classification="comic", review_status="matched"
    )
    assert after_matched == []


@pytest.mark.req("FRG-SRC-004")
async def test_patch_rejects_unknown_field_and_empty_body(app_client):
    """The PATCH body is extensible but ``extra="forbid"``: an unknown key is a
    400, and a body that sets nothing is a 400 (FRG-SRC-004)."""
    app = app_client.app
    source_id = await _populate(app)

    unknown = app_client.patch(
        f"/api/v1/sources/{source_id}", json={"auto_sync": True, "bogus": 1}
    )
    assert unknown.status_code == 400

    empty = app_client.patch(f"/api/v1/sources/{source_id}", json={})
    assert empty.status_code == 400
    assert empty.json()["errors"][0]["field"] == "auto_sync"


@pytest.mark.req("FRG-SRC-004")
async def test_patch_unknown_source_is_404(app_client):
    """PATCH against an unknown source id is a 404 (FRG-SRC-004)."""
    app_client.app  # noqa: B018 — ensure the app/db fixtures are live
    resp = app_client.patch("/api/v1/sources/9999", json={"auto_sync": True})
    assert resp.status_code == 404
