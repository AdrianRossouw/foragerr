"""Review-first entitlement workflow (FRG-SRC-004): match/add/ignore/restore
(single + bulk), accept-gates-download, decision survival across re-sync, and
the auto-sync toggle (default OFF; opt-in accepts only confident matches).
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from foragerr.library import repo as library_repo
from foragerr.sources import ratelimit, repo, review
from foragerr.sources.enrich import enrich_source
from foragerr.sources.models import SourceEntitlementRow
from foragerr.sources.registry import TYPE_HUMBLE
from foragerr.sources.service import run_sync
from foragerr.sources.settings import HumbleSettings
from http_support import make_settings
from sources_support import (  # noqa: F401 — imported fixtures
    fixture_bytes,
    format_profile_id,
    make_factory,
    order_handler,
    root_folder_id,
)

GAMEKEY = "aBcD1234synthetic"


@pytest.fixture(autouse=True)
def _reset_gates():
    ratelimit.reset_gates()
    yield
    ratelimit.reset_gates()


class FakeCommands:
    """Records enqueued commands (the grab hand-off) without a real queue."""

    def __init__(self):
        self.enqueued: list[tuple] = []

    async def enqueue(self, name, payload=None, *, triggered_by="manual"):
        self.enqueued.append((name, payload, triggered_by))
        return SimpleNamespace(id=len(self.enqueued), status="queued")


async def _source(db, *, auto_sync=False):
    return await repo.create_source(
        db,
        source_type=TYPE_HUMBLE,
        name="Humble Bundle",
        settings=HumbleSettings(session_cookie="SYNTH-COOKIE"),
        auto_sync=auto_sync,
    )


async def _synced_source(db, config_dir, *, auto_sync=False):
    source = await _source(db, auto_sync=auto_sync)
    handler = order_handler(
        list_body=b'[{"gamekey":"%s"}]' % GAMEKEY.encode(),
        order_bodies={GAMEKEY: fixture_bytes("order_comics.json")},
    )
    factory = make_factory(config_dir, httpx.MockTransport(handler))
    await run_sync(db, factory, source, min_interval=0.0)
    return source


async def _comic(db, source_id, machine_name) -> SourceEntitlementRow:
    for e in await repo.list_entitlements(db, source_id, classification="comic"):
        if e.machine_name == machine_name:
            return e
    raise AssertionError(f"no entitlement {machine_name}")


async def _mk_series(db, root_folder_id, format_profile_id, *, cvid, title):
    async with db.write_session() as session:
        series = await library_repo.create_series(
            session,
            cv_volume_id=cvid,
            title=title,
            format_profile_id=format_profile_id,
            root_folder_id=root_folder_id,
            path=f"/tmp/comics/{title} ({cvid})",
        )
        return series.id


# --- match + accept-gates-download ------------------------------------------


@pytest.mark.req("FRG-SRC-004")
async def test_match_links_series_and_queues_grab(
    db, config_dir, root_folder_id, format_profile_id
):
    source = await _synced_source(db, config_dir)
    series_id = await _mk_series(
        db, root_folder_id, format_profile_id, cvid=555, title="Synthetic Hero"
    )
    ent = await _comic(db, source.id, "synth_singleissue_01")
    commands = FakeCommands()

    row = await review.match_entitlement(
        db, ent.id, series_id=series_id, commands=commands
    )
    assert row.review_status == "matched"
    assert row.matched_series_id == series_id
    # Accept queues the grab (the accept action IS the download gate).
    assert row.download_state == "queued"
    assert commands.enqueued == [
        ("source-grab", {"entitlement_id": ent.id}, "accept")
    ]


@pytest.mark.req("FRG-SRC-004")
async def test_default_sync_downloads_nothing(db, config_dir):
    """No download or library mutation on a default (auto_sync OFF) source."""
    source = await _synced_source(db, config_dir, auto_sync=False)
    commands = FakeCommands()
    settings = make_settings(config_dir)

    summary = await enrich_source(
        db, settings, source, commands=commands, cv_client=None
    )
    assert "auto_sync=off" in summary
    # Nothing accepted, nothing queued, every comic still awaiting review.
    assert commands.enqueued == []
    comics = await repo.list_entitlements(db, source.id, classification="comic")
    assert all(e.review_status == "new" for e in comics)
    assert all(e.download_state is None for e in comics)


# --- ignore + restore -------------------------------------------------------


@pytest.mark.req("FRG-SRC-004")
async def test_ignore_then_restore_recomputes_proposal(
    db, config_dir, root_folder_id, format_profile_id
):
    source = await _synced_source(db, config_dir)
    await _mk_series(
        db, root_folder_id, format_profile_id, cvid=556, title="Synthetic Hero"
    )
    ent = await _comic(db, source.id, "synth_singleissue_01")

    ignored = await review.ignore_entitlement(db, ent.id)
    assert ignored.review_status == "ignored"

    restored = await review.restore_entitlement(db, ent.id)
    assert restored.review_status == "new"
    assert restored.matched_series_id is None
    # Restore recomputes the proposed match (library-first) — a confident one.
    assert restored.proposed_series_id is not None
    assert restored.proposed_match_json is not None


# --- decision survives a re-sync (idempotency) ------------------------------


@pytest.mark.req("FRG-SRC-004")
async def test_operator_decision_survives_resync(
    db, config_dir, root_folder_id, format_profile_id
):
    source = await _synced_source(db, config_dir)
    series_id = await _mk_series(
        db, root_folder_id, format_profile_id, cvid=557, title="Synthetic Hero"
    )
    ent = await _comic(db, source.id, "synth_singleissue_01")
    await review.match_entitlement(db, ent.id, series_id=series_id, commands=None)
    ignored = await _comic(db, source.id, "synth_collected_edition_vol1")
    await review.ignore_entitlement(db, ignored.id)

    # Re-sync: the diff refreshes display fields but must preserve decisions.
    handler = order_handler(
        list_body=b'[{"gamekey":"%s"}]' % GAMEKEY.encode(),
        order_bodies={GAMEKEY: fixture_bytes("order_comics.json")},
    )
    factory = make_factory(config_dir, httpx.MockTransport(handler))
    await run_sync(db, factory, source, min_interval=0.0)

    after_match = await repo.get_entitlement(db, ent.id)
    after_ignore = await repo.get_entitlement(db, ignored.id)
    assert after_match.review_status == "matched"
    assert after_match.matched_series_id == series_id
    assert after_ignore.review_status == "ignored"


# --- bulk -------------------------------------------------------------------


@pytest.mark.req("FRG-SRC-004")
async def test_bulk_ignore_then_bulk_restore(db, config_dir):
    source = await _synced_source(db, config_dir)
    comics = await repo.list_entitlements(db, source.id, classification="comic")
    ids = [e.id for e in comics]

    result = await review.bulk_ignore(db, ids)
    assert result.applied == len(ids)
    statuses = [(await repo.get_entitlement(db, i)).review_status for i in ids]
    assert statuses == ["ignored"] * len(ids)

    restored = await review.bulk_restore(db, ids)
    assert restored.applied == len(ids)
    statuses = [(await repo.get_entitlement(db, i)).review_status for i in ids]
    assert statuses == ["new"] * len(ids)


# --- auto-sync (opt-in) -----------------------------------------------------


@pytest.mark.req("FRG-SRC-004")
async def test_auto_sync_accepts_only_confident_matches(
    db, config_dir, root_folder_id, format_profile_id
):
    source = await _synced_source(db, config_dir, auto_sync=True)
    await _mk_series(
        db, root_folder_id, format_profile_id, cvid=558, title="Synthetic Hero"
    )
    commands = FakeCommands()
    settings = make_settings(config_dir)

    summary = await enrich_source(
        db, settings, source, commands=commands, cv_client=None
    )
    assert "auto_sync=on" in summary

    # The single issue confidently matches "Synthetic Hero" → auto-accepted +
    # grab queued; the collected edition scores below threshold → stays new.
    single = await _comic(db, source.id, "synth_singleissue_01")
    collected = await _comic(db, source.id, "synth_collected_edition_vol1")
    assert single.review_status == "matched"
    assert single.download_state == "queued"
    assert collected.review_status == "new"
    assert collected.download_state is None
    assert commands.enqueued == [
        ("source-grab", {"entitlement_id": single.id}, "accept")
    ]
