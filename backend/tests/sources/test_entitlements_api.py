"""Entitlement review HTTP surface (FRG-SRC-004): list/detail/actions/bulk.

Entitlements are populated by running the sync service directly against the
app's database (the queue-driven "Sync now" is covered in test_sources_api);
these tests exercise the review endpoints themselves.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from conftest import running_app
from foragerr.library import repo as library_repo
from foragerr.quality.models import DEFAULT_PROFILE_NAME, FormatProfileRow
from foragerr.sources import ratelimit, repo
from foragerr.sources.models import SourceEntitlementRow
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
async def app_client(tmp_path: Path):
    """The app driven on the TEST's own event loop (see ``running_app``): these
    tests mix HTTP calls with direct ``app.state.db`` awaits, which is only safe
    when there is exactly one loop."""
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    async with running_app(make_settings(cfg)) as (_app, client):
        yield client


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

    comics = (
        await app_client.get(
            f"/api/v1/sources/{source_id}/entitlements?classification=comic"
        )
    ).json()
    assert len(comics) == 3
    assert all(c["classification"] == "comic" for c in comics)
    # The cookie/md5 internals are not needed by the review UI shape, but the
    # review + download axes are present.
    assert {"review_status", "download_state"} <= set(comics[0])

    detail = (
        await app_client.get(f"/api/v1/sources/entitlements/{comics[0]['id']}")
    ).json()
    assert detail["id"] == comics[0]["id"]
    assert detail["fill_sets"] == []  # no matched series yet


@pytest.mark.req("FRG-SRC-004")
async def test_ignore_restore_roundtrip(app_client):
    app = app_client.app
    source_id = await _populate(app)
    eid = await _first_comic_id(app, source_id)

    ignored = (
        await app_client.post(f"/api/v1/sources/entitlements/{eid}/ignore")
    ).json()
    assert ignored["review_status"] == "ignored"

    restored = (
        await app_client.post(f"/api/v1/sources/entitlements/{eid}/restore")
    ).json()
    assert restored["review_status"] == "new"


@pytest.mark.req("FRG-SRC-004")
async def test_restore_endpoint_refuses_a_row_that_is_not_ignored(app_client):
    """Restore is the inverse of ignore and destructive to anything else (it
    clears the match target and overwrites the proposal), so a non-ignored row
    is a 409 through the surface too — the per-row error the bulk form reports
    is the same refusal."""
    app = app_client.app
    source_id = await _populate(app)
    eid = await _first_comic_id(app, source_id)

    resp = await app_client.post(f"/api/v1/sources/entitlements/{eid}/restore")
    assert resp.status_code == 409
    assert (await repo.get_entitlement(app.state.db, eid)).review_status == "new"


@pytest.mark.req("FRG-SRC-010")
async def test_restore_endpoint_threads_a_comicvine_client_when_one_exists(
    app_client, monkeypatch
):
    """The endpoint owns the CV client for this operator-initiated action: it
    builds one when a key is configured, passes it (with the ``cv_configured``
    fact) into the action, and always closes it.

    Without this the restore recomputed library-only and stamped a
    ``library-fallback`` proposal — rendered by the review screen as a catalog
    verdict — on a deployment that has a ComicVine key.
    """
    import foragerr.api.sources as api_sources

    app = app_client.app
    source_id = await _populate(app)
    eid = await _first_comic_id(app, source_id)
    await app_client.post(f"/api/v1/sources/entitlements/{eid}/ignore")

    seen: dict = {}

    class _FakeCV:
        def __init__(self):
            self.closed = False

        async def suggest_series(self, term):
            from types import SimpleNamespace

            seen["term"] = term
            return SimpleNamespace(candidates=[])

        async def aclose(self):
            self.closed = True

    fake = _FakeCV()
    monkeypatch.setattr(
        "foragerr.sources.enrich.build_cv_client", lambda settings: fake
    )
    assert api_sources._operator_cv_client  # the seam under test

    resp = await app_client.post(f"/api/v1/sources/entitlements/{eid}/restore")
    assert resp.status_code == 200
    assert resp.json()["review_status"] == "new"
    assert seen.get("term")  # ComicVine WAS consulted
    assert fake.closed is True  # ...and the client was closed
    # CV answered with nothing, so the row carries the catalog verdict — never a
    # library-fallback proposal dressed as one.
    assert resp.json()["proposed_match"]["universe"] == "comicvine"


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

    resp = await app_client.post(
        f"/api/v1/sources/entitlements/{eid}/match", json={"series_id": series_id}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["review_status"] == "matched"
    assert body["matched_series_id"] == series_id


class _FakeCommands:
    """Stands in for ``app.state.commands`` so an accepted grab is recorded
    rather than actually dispatched to a worker mid-assertion."""

    def __init__(self, real):
        self.enqueued: list[tuple] = []
        self._real = real

    async def enqueue(self, name, payload=None, *, triggered_by="manual"):
        from types import SimpleNamespace

        self.enqueued.append((name, payload, triggered_by))
        return SimpleNamespace(id=len(self.enqueued), status="queued")

    async def drain(self, *args, **kwargs):
        # The app's shutdown hook drains whatever sits on app.state.commands —
        # forward to the real service so its workers still stop cleanly.
        return await self._real.drain(*args, **kwargs)


async def _series_with_cv(app, *, cv_volume_id: int, title: str) -> int:
    """A library series carrying ``cv_volume_id`` (root folder + profile wired)."""
    from sqlalchemy import select

    async with app.state.db.read_session() as session:
        fp_id = (
            await session.execute(
                select(FormatProfileRow.id).where(
                    FormatProfileRow.name == DEFAULT_PROFILE_NAME
                )
            )
        ).scalar_one()
    root = Path(app.state.settings.config_dir) / f"root-{cv_volume_id}"
    root.mkdir()
    async with app.state.db.write_session() as session:
        rf = await library_repo.create_root_folder(session, str(root))
        series = await library_repo.create_series(
            session,
            cv_volume_id=cv_volume_id,
            title=title,
            format_profile_id=fp_id,
            root_folder_id=rf.id,
            path=str(root / title),
        )
        return series.id


@pytest.mark.req("FRG-SRC-008")
async def test_add_endpoint_degrades_to_match_when_volume_is_in_library(app_client):
    """POST /add on a volume that is ALREADY a library series matches it instead
    of 400-ing (FRG-SRC-008) — the same outcome as the match action. Nothing
    reaches ComicVine (no key is configured here), so a real add would fail."""
    app = app_client.app
    source_id = await _populate(app)
    eid = await _first_comic_id(app, source_id)
    series_id = await _series_with_cv(app, cv_volume_id=9100, title="Synthetic Hero")
    app.state.commands = _FakeCommands(app.state.commands)

    resp = await app_client.post(
        f"/api/v1/sources/entitlements/{eid}/add", json={"cv_volume_id": 9100}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["review_status"] == "matched"
    assert body["matched_series_id"] == series_id
    # Accepting queues the grab exactly as a match would.
    assert body["download_state"] == "queued"
    assert app.state.commands.enqueued == [
        ("source-grab", {"entitlement_id": eid}, "accept")
    ]


@pytest.mark.req("FRG-SRC-009")
async def test_retry_download_endpoint_requeues_then_conflicts(app_client):
    """POST /retry-download clears the failure and re-queues (FRG-SRC-009); a
    second retry — now queued, not failed — is a 409 with no state change."""
    app = app_client.app
    source_id = await _populate(app)
    eid = await _first_comic_id(app, source_id)
    app.state.commands = _FakeCommands(app.state.commands)

    async with app.state.db.write_session() as session:
        row = await session.get(SourceEntitlementRow, eid)
        row.review_status = "matched"
        row.download_state = "failed"
        row.download_error = "md5 mismatch on the downloaded file"

    resp = await app_client.post(f"/api/v1/sources/entitlements/{eid}/retry-download")
    assert resp.status_code == 200
    body = resp.json()
    assert body["download_state"] == "queued"
    assert body["download_error"] is None
    assert app.state.commands.enqueued == [
        ("source-grab", {"entitlement_id": eid}, "accept")
    ]

    conflict = await app_client.post(
        f"/api/v1/sources/entitlements/{eid}/retry-download"
    )
    assert conflict.status_code == 409
    after = await repo.get_entitlement(app.state.db, eid)
    assert after.download_state == "queued"  # unchanged by the rejected retry
    assert len(app.state.commands.enqueued) == 1  # and never a second grab


@pytest.mark.req("FRG-SRC-009")
async def test_retry_download_unknown_entitlement_is_404(app_client):
    app_client.app  # noqa: B018 — ensure the app/db fixtures are live
    resp = await app_client.post("/api/v1/sources/entitlements/999999/retry-download")
    assert resp.status_code == 404


@pytest.mark.req("FRG-SRC-004")
async def test_bulk_ignore_endpoint(app_client):
    app = app_client.app
    source_id = await _populate(app)
    comics = await repo.list_entitlements(app.state.db, source_id, classification="comic")
    ids = [c.id for c in comics]

    resp = await app_client.post(
        "/api/v1/sources/entitlements/bulk",
        json={"action": "ignore", "entitlement_ids": ids},
    )
    assert resp.status_code == 200
    assert resp.json()["applied"] == len(ids)

    remaining = (
        await app_client.get(
            f"/api/v1/sources/{source_id}"
            "/entitlements?review_status=new&classification=comic"
        )
    ).json()
    assert remaining == []


@pytest.mark.req("FRG-SRC-004")
async def test_bulk_match_requires_series_id(app_client):
    app = app_client.app
    source_id = await _populate(app)
    comics = await repo.list_entitlements(app.state.db, source_id, classification="comic")
    resp = await app_client.post(
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
    assert (await app_client.get("/api/v1/sources")).json()[0]["auto_sync"] is False

    on = await app_client.patch(f"/api/v1/sources/{source_id}", json={"auto_sync": True})
    assert on.status_code == 200
    assert on.json()["auto_sync"] is True
    assert (await app_client.get("/api/v1/sources")).json()[0]["auto_sync"] is True

    off = await app_client.patch(f"/api/v1/sources/{source_id}", json={"auto_sync": False})
    assert off.status_code == 200
    assert off.json()["auto_sync"] is False
    assert (await app_client.get("/api/v1/sources")).json()[0]["auto_sync"] is False
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

    resp = await app_client.patch(f"/api/v1/sources/{source_id}", json={"auto_sync": True})
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

    unknown = await app_client.patch(
        f"/api/v1/sources/{source_id}", json={"auto_sync": True, "bogus": 1}
    )
    assert unknown.status_code == 400

    empty = await app_client.patch(f"/api/v1/sources/{source_id}", json={})
    assert empty.status_code == 400
    assert empty.json()["errors"][0]["field"] == "auto_sync"


@pytest.mark.req("FRG-SRC-004")
async def test_patch_unknown_source_is_404(app_client):
    """PATCH against an unknown source id is a 404 (FRG-SRC-004)."""
    app_client.app  # noqa: B018 — ensure the app/db fixtures are live
    resp = await app_client.patch("/api/v1/sources/9999", json={"auto_sync": True})
    assert resp.status_code == 404


# --- explicit operator provenance at the API boundary (design D7) ------------


@pytest.mark.req("FRG-SRC-004")
async def test_match_endpoint_stamps_operator_provenance_explicitly(app_client):
    """The endpoints pass ``MATCHED_VIA_OPERATOR`` themselves rather than
    inheriting a default (FRG-PP-022 guard 3 / D7): a human hit this route, so
    the stamp is asserted here, at the boundary that knows it."""
    app = app_client.app
    source_id = await _populate(app)
    eid = await _first_comic_id(app, source_id)
    series_id = await _series_with_cv(app, cv_volume_id=9300, title="Synthetic Hero")
    app.state.commands = _FakeCommands(app.state.commands)

    resp = await app_client.post(
        f"/api/v1/sources/entitlements/{eid}/match", json={"series_id": series_id}
    )
    assert resp.status_code == 200
    assert (await repo.get_entitlement(app.state.db, eid)).matched_via == "operator"


@pytest.mark.req("FRG-SRC-004")
async def test_add_endpoint_stamps_operator_provenance_explicitly(app_client):
    app = app_client.app
    source_id = await _populate(app)
    eid = await _first_comic_id(app, source_id)
    await _series_with_cv(app, cv_volume_id=9301, title="Synthetic Hero")
    app.state.commands = _FakeCommands(app.state.commands)

    resp = await app_client.post(
        f"/api/v1/sources/entitlements/{eid}/add", json={"cv_volume_id": 9301}
    )
    assert resp.status_code == 200
    assert (await repo.get_entitlement(app.state.db, eid)).matched_via == "operator"


# --- bulk accept (FRG-SRC-011) ----------------------------------------------


async def _set_library_proposal(app, entitlement_id: int, series_id: int) -> None:
    import json

    async with app.state.db.write_session() as session:
        row = await session.get(SourceEntitlementRow, entitlement_id)
        row.proposed_series_id = series_id
        row.proposed_match_json = json.dumps(
            {
                "kind": "library",
                "series_id": series_id,
                "cv_volume_id": None,
                "title": "Synthetic Hero",
                "year": 2019,
                "confidence": 0.9,
                "auto": False,
                "candidates": [],
            },
            sort_keys=True,
        )


@pytest.mark.req("FRG-SRC-011")
async def test_bulk_accept_endpoint_applies_each_rows_own_proposal(app_client):
    """``accept`` carries NO series_id — every row resolves to its own stored
    proposal, and an un-proposed row is reported under its id while the rest
    still apply (the request itself is a 200)."""
    app = app_client.app
    source_id = await _populate(app)
    comics = await repo.list_entitlements(
        app.state.db, source_id, classification="comic"
    )
    series_id = await _series_with_cv(app, cv_volume_id=9302, title="Synthetic Hero")
    proposed, bare = comics[0], comics[1]
    await _set_library_proposal(app, proposed.id, series_id)
    app.state.commands = _FakeCommands(app.state.commands)

    resp = await app_client.post(
        "/api/v1/sources/entitlements/bulk",
        json={"action": "accept", "entitlement_ids": [proposed.id, bare.id]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["applied"] == 1
    assert body["skipped"] == 1
    # The wire keys are STRINGS: ``BulkResult.errors`` is keyed by int and JSON
    # object keys can only be strings, so the client indexes by ``String(id)``.
    # Asserting through a ``{str(k) for k in ...}`` normalisation hid that — it
    # passed whether the server sent ints or strings, so it pinned nothing.
    assert set(body["errors"]) == {str(bare.id)}
    assert all(isinstance(k, str) for k in body["errors"])

    after = await repo.get_entitlement(app.state.db, proposed.id)
    assert (after.review_status, after.matched_series_id) == ("matched", series_id)
    assert after.matched_via == "operator"
    assert (await repo.get_entitlement(app.state.db, bare.id)).review_status == "new"


@pytest.mark.req("FRG-SRC-011")
async def test_bulk_rejects_an_unknown_action_by_name(app_client):
    app = app_client.app
    source_id = await _populate(app)
    comics = await repo.list_entitlements(
        app.state.db, source_id, classification="comic"
    )
    resp = await app_client.post(
        "/api/v1/sources/entitlements/bulk",
        json={"action": "obliterate", "entitlement_ids": [comics[0].id]},
    )
    assert resp.status_code == 400
    assert "accept" in resp.json()["errors"][0]["message"]
