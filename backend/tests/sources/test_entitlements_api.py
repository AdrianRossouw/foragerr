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
        # ``**_`` absorbs the lane the operator seam now declares (FRG-META-022):
        # this test is about the client being threaded and closed, not the lane.
        "foragerr.sources.enrich.build_cv_client", lambda settings, **_: fake
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


@pytest.mark.req("FRG-SRC-014")
async def test_bulk_apply_to_group_in_library_endpoint(app_client):
    """The apply_to_group action with a ``series_id`` bulk-matches every listed
    member through the surface (FRG-SRC-014)."""
    app = app_client.app
    source_id = await _populate(app)
    series_id = await _series_with_cv(app, cv_volume_id=7014, title="Synthetic Hero")
    comics = await repo.list_entitlements(
        app.state.db, source_id, classification="comic", review_status="new"
    )
    ids = [c.id for c in comics]

    resp = await app_client.post(
        "/api/v1/sources/entitlements/bulk",
        json={
            "action": "apply_to_group",
            "entitlement_ids": ids,
            "series_id": series_id,
        },
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


@pytest.mark.req("FRG-SRC-014")
async def test_bulk_apply_to_group_requires_a_target(app_client):
    """apply_to_group with neither a series_id nor a cv_volume_id is a 422."""
    app = app_client.app
    source_id = await _populate(app)
    comics = await repo.list_entitlements(app.state.db, source_id, classification="comic")
    resp = await app_client.post(
        "/api/v1/sources/entitlements/bulk",
        json={"action": "apply_to_group", "entitlement_ids": [comics[0].id]},
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


async def _browse_only_series(app) -> int:
    """A series on a read-only reference root."""
    from sqlalchemy import select

    async with app.state.db.read_session() as session:
        fp_id = (
            await session.execute(
                select(FormatProfileRow.id).where(
                    FormatProfileRow.name == DEFAULT_PROFILE_NAME
                )
            )
        ).scalar_one()
    reference = Path(app.state.settings.config_dir) / "reference-library"
    reference.mkdir()
    async with app.state.db.write_session() as session:
        rf = await library_repo.create_root_folder(
            session, str(reference), read_only=True
        )
        series = await library_repo.create_series(
            session,
            cv_volume_id=9101,
            title="Example Reference Series",
            format_profile_id=fp_id,
            root_folder_id=rf.id,
            path=str(reference / "Example Reference Series"),
        )
        return series.id


@pytest.mark.req("FRG-SER-022")
async def test_match_and_bulk_match_answer_the_read_only_409_shape(app_client):
    """The refusal has to reach the client as the SAME 409 every other read-only
    surface returns — the UI classifies on the ``read_only`` field, not on
    message text — through the single action route and the bulk one."""
    app = app_client.app
    source_id = await _populate(app)
    eid = await _first_comic_id(app, source_id)
    series_id = await _browse_only_series(app)

    single = await app_client.post(
        f"/api/v1/sources/entitlements/{eid}/match", json={"series_id": series_id}
    )
    bulk = await app_client.post(
        "/api/v1/sources/entitlements/bulk",
        json={"action": "match", "entitlement_ids": [eid], "series_id": series_id},
    )

    for resp in (single, bulk):
        assert resp.status_code == 409
        body = resp.json()
        assert set(body) == {"message", "errors"}
        assert [e["field"] for e in body["errors"]] == ["read_only"]
    after = await repo.get_entitlement(app.state.db, eid)
    assert after.review_status == "new"
    assert after.matched_series_id is None


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
    message = resp.json()["errors"][0]["message"]
    # The message IS the action vocabulary, so every action the bar can send has
    # to appear in it — a name missing here reads as unsupported.
    for action in (
        "ignore",
        "restore",
        "match",
        "accept",
        "apply_to_group",
        "mark_non_comic",
        "mark_comic",
    ):
        assert action in message


# --- the deferred proposals a bulk restore leaves behind (FRG-SRC-004) -------


@pytest.fixture
async def keyed_app_client(tmp_path: Path):
    """The same app, on a deployment that HAS a ComicVine key."""
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    async with running_app(
        make_settings(cfg, comicvine_api_key="CV-SECRET-KEY-abc123")
    ) as (_app, client):
        yield client


@pytest.mark.req("FRG-SRC-004")
async def test_bulk_restore_asks_for_the_proposals_it_deferred(keyed_app_client):
    """Deferring the proposals must not mean waiting a day for them.

    The rows come back to review un-proposed, and an un-proposed row refuses
    every accept — so "Select all → Restore" followed by "Select all → Accept"
    was a screen of refusals until the next scheduled sync ran the enrichment
    pass. The endpoint therefore enqueues the recompute command for the source
    it just restored into: once per source however many rows moved, and once
    however many restores the operator runs while it is still queued.
    """
    app = keyed_app_client.app
    source_id = await _populate(app)
    comics = await repo.list_entitlements(
        app.state.db, source_id, classification="comic", review_status="new"
    )
    ids = [c.id for c in comics]
    for eid in ids:
        await keyed_app_client.post(f"/api/v1/sources/entitlements/{eid}/ignore")
    app.state.commands = _FakeCommands(app.state.commands)

    resp = await keyed_app_client.post(
        "/api/v1/sources/entitlements/bulk",
        json={"action": "restore", "entitlement_ids": ids},
    )

    assert resp.json()["applied"] == len(ids)
    assert app.state.commands.enqueued == [
        (
            "source-recompute-proposals",
            {"source_id": source_id, "include_markers": False},
            "manual",
        )
    ]


@pytest.mark.req("FRG-SRC-004")
async def test_a_wholly_refused_bulk_restore_asks_for_nothing(keyed_app_client):
    """No row moved, so no proposal was deferred and there is nothing to fill —
    an enqueue here would put a command on the operator's queue for an action
    that changed nothing."""
    app = keyed_app_client.app
    source_id = await _populate(app)
    eid = await _first_comic_id(app, source_id)  # still ``new``: unrestorable
    app.state.commands = _FakeCommands(app.state.commands)

    resp = await keyed_app_client.post(
        "/api/v1/sources/entitlements/bulk",
        json={"action": "restore", "entitlement_ids": [eid]},
    )

    assert resp.json()["applied"] == 0
    assert app.state.commands.enqueued == []


@pytest.mark.req("FRG-SRC-004")
async def test_a_keyless_bulk_restore_enqueues_no_recompute(app_client):
    """The recompute command refuses to run without a ComicVine key, so
    enqueueing it here would only add a guaranteed no-op to the command surface.
    The restore itself still happens — those rows re-enter the ordinary
    enrichment pass, which is where a keyless deployment's proposals come from.
    """
    app = app_client.app
    source_id = await _populate(app)
    eid = await _first_comic_id(app, source_id)
    await app_client.post(f"/api/v1/sources/entitlements/{eid}/ignore")
    app.state.commands = _FakeCommands(app.state.commands)

    resp = await app_client.post(
        "/api/v1/sources/entitlements/bulk",
        json={"action": "restore", "entitlement_ids": [eid]},
    )

    assert resp.json()["applied"] == 1
    assert app.state.commands.enqueued == []
    assert (await repo.get_entitlement(app.state.db, eid)).review_status == "new"


# --- operator classification (FRG-SRC-016) -----------------------------------


@pytest.mark.req("FRG-SRC-016")
async def test_classify_endpoint_marks_a_row_and_exposes_its_provenance(app_client):
    """The single-row mark through the surface: the response carries the new
    classification AND the operator provenance the review screen reads to know
    the row will not move again."""
    app = app_client.app
    source_id = await _populate(app)
    eid = await _first_comic_id(app, source_id)

    resp = await app_client.post(
        f"/api/v1/sources/entitlements/{eid}/classify",
        json={"classification": "other"},
    )

    assert resp.status_code == 200
    assert resp.json()["classification"] == "other"
    assert resp.json()["classified_via"] == "operator"
    listed = (
        await app_client.get(
            f"/api/v1/sources/{source_id}/entitlements?classification=other"
        )
    ).json()
    assert eid in [row["id"] for row in listed]


@pytest.mark.req("FRG-SRC-016")
async def test_classify_endpoint_rejects_an_unknown_classification(app_client):
    app = app_client.app
    source_id = await _populate(app)
    eid = await _first_comic_id(app, source_id)

    resp = await app_client.post(
        f"/api/v1/sources/entitlements/{eid}/classify",
        json={"classification": "sourcebook"},
    )

    assert resp.status_code == 422
    after = await repo.get_entitlement(app.state.db, eid)
    assert (after.classification, after.classified_via) == ("comic", None)


@pytest.mark.req("FRG-SRC-016")
async def test_classify_endpoint_refuses_an_ignored_row(app_client):
    app = app_client.app
    source_id = await _populate(app)
    eid = await _first_comic_id(app, source_id)
    await app_client.post(f"/api/v1/sources/entitlements/{eid}/ignore")

    resp = await app_client.post(
        f"/api/v1/sources/entitlements/{eid}/classify",
        json={"classification": "other"},
    )

    assert resp.status_code == 409
    assert "restore it first" in resp.json()["message"]
    after = await repo.get_entitlement(app.state.db, eid)
    assert (after.classification, after.classified_via) == ("comic", None)


@pytest.mark.req("FRG-SRC-016")
async def test_bulk_marks_by_action_name_in_both_directions(app_client):
    """The bulk vocabulary carries the classification in the ACTION, so a
    selection can only be marked with a value the bar offers."""
    app = app_client.app
    source_id = await _populate(app)
    comics = await repo.list_entitlements(
        app.state.db, source_id, classification="comic", review_status="new"
    )
    ids = [c.id for c in comics]

    marked = await app_client.post(
        "/api/v1/sources/entitlements/bulk",
        json={"action": "mark_non_comic", "entitlement_ids": ids},
    )
    assert marked.status_code == 200
    assert marked.json()["applied"] == len(ids)
    assert (
        await app_client.get(
            f"/api/v1/sources/{source_id}"
            "/entitlements?review_status=new&classification=comic"
        )
    ).json() == []

    back = await app_client.post(
        "/api/v1/sources/entitlements/bulk",
        json={"action": "mark_comic", "entitlement_ids": ids},
    )
    assert back.json()["applied"] == len(ids)
    restored = (
        await app_client.get(
            f"/api/v1/sources/{source_id}"
            "/entitlements?review_status=new&classification=comic"
        )
    ).json()
    assert {row["id"] for row in restored} == set(ids)
    assert all(row["classified_via"] == "operator" for row in restored)


@pytest.mark.req("FRG-SRC-016")
async def test_bulk_mark_reports_the_unmarkable_rows_per_row(app_client):
    """A selection that spans review buckets marks what it can and names the
    rest — the batch is never vetoed by one decided row."""
    app = app_client.app
    source_id = await _populate(app)
    comics = await repo.list_entitlements(
        app.state.db, source_id, classification="comic", review_status="new"
    )
    markable, ignored = comics[0].id, comics[1].id
    await app_client.post(f"/api/v1/sources/entitlements/{ignored}/ignore")

    resp = await app_client.post(
        "/api/v1/sources/entitlements/bulk",
        json={"action": "mark_non_comic", "entitlement_ids": [markable, ignored]},
    )

    body = resp.json()
    assert (body["applied"], body["skipped"]) == (1, 1)
    assert "restore it first" in body["errors"][str(ignored)]
    assert (await repo.get_entitlement(app.state.db, markable)).classification == "other"
