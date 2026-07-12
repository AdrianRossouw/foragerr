"""Entitlement sync: diff, idempotency, classification, malformed-skip, and the
session-expiry state machine (FRG-SRC-003/005)."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from foragerr.sources import ratelimit
from foragerr.sources.commands import _sync_one
from foragerr.sources.models import SourceEntitlementRow, SourceRow
from foragerr.sources.registry import TYPE_HUMBLE
from foragerr.sources.repo import create_source, get_source
from foragerr.sources.service import reconnect_source as service_reconnect
from foragerr.sources.service import run_sync
from foragerr.sources.settings import HumbleSettings
from sources_support import fixture_bytes, make_factory, order_handler

GAMEKEY = "aBcD1234synthetic"


@pytest.fixture(autouse=True)
def _reset_gates():
    ratelimit.reset_gates()
    yield
    ratelimit.reset_gates()


async def _source(db) -> SourceRow:
    return await create_source(
        db,
        source_type=TYPE_HUMBLE,
        name="Humble Bundle",
        settings=HumbleSettings(session_cookie="SYNTH-COOKIE"),
    )


def _factory(config_dir, handler):
    return make_factory(config_dir, httpx.MockTransport(handler))


def _one_order_handler():
    return order_handler(
        list_body=b'[{"gamekey":"%s"}]' % GAMEKEY.encode(),
        order_bodies={GAMEKEY: fixture_bytes("order_comics.json")},
    )


async def _entitlements(db) -> list[SourceEntitlementRow]:
    async with db.read_session() as session:
        return list(
            (await session.execute(select(SourceEntitlementRow))).scalars().all()
        )


@pytest.mark.req("FRG-SRC-003")
async def test_sync_creates_entitlements_with_classification(db, config_dir):
    source = await _source(db)
    factory = _factory(config_dir, _one_order_handler())
    result = await run_sync(db, factory, source, min_interval=0.0)

    assert result.orders == 1
    assert result.new_entitlements == 6  # 7 subproducts, 1 malformed skipped
    assert result.comic == 3  # twins + collected + pdf-only artbook
    assert result.other == 3  # epub-only + game + prose-with-pdf

    ents = {e.machine_name: e for e in await _entitlements(db)}
    assert ents["synth_singleissue_01"].classification == "comic"
    assert ents["synth_singleissue_01"].review_status == "new"
    assert ents["synth_singleissue_01"].preferred_format == "CBZ"
    # Proposed-match seam is left NULL for worker A2.
    assert ents["synth_singleissue_01"].proposed_series_id is None
    assert ents["synth_singleissue_01"].proposed_match_json is None
    assert ents["synth_singleissue_01"].matched_series_id is None
    # Non-comic items are retained, not dropped.
    assert ents["synth_video_game_title"].classification == "other"


@pytest.mark.req("FRG-SRC-003")
async def test_resync_is_idempotent_and_preserves_decisions(db, config_dir):
    source = await _source(db)
    factory = _factory(config_dir, _one_order_handler())
    await run_sync(db, factory, source, min_interval=0.0)

    # Operator matches one item; a re-sync must NOT reset it or duplicate rows.
    async with db.write_session() as session:
        row = (
            await session.execute(
                select(SourceEntitlementRow).where(
                    SourceEntitlementRow.machine_name == "synth_singleissue_01"
                )
            )
        ).scalar_one()
        row.review_status = "matched"
        row.matched_series_id = 42

    factory2 = _factory(config_dir, _one_order_handler())
    result = await run_sync(db, factory2, source, min_interval=0.0)
    assert result.new_entitlements == 0
    assert result.updated_entitlements == 6

    ents = await _entitlements(db)
    assert len(ents) == 6  # no duplicates
    matched = next(e for e in ents if e.machine_name == "synth_singleissue_01")
    assert matched.review_status == "matched"  # decision preserved
    assert matched.matched_series_id == 42


@pytest.mark.req("FRG-SRC-003")
async def test_malformed_order_is_skipped_partial_kept(db, config_dir):
    source = await _source(db)
    g1, g2 = "goodkey", "badkey"
    handler = order_handler(
        list_body=b'[{"gamekey":"goodkey"},{"gamekey":"badkey"}]',
        order_bodies={
            g1: fixture_bytes("order_comics.json"),
            g2: b"this is not valid json",
        },
    )
    result = await run_sync(db, _factory(config_dir, handler), source, min_interval=0.0)
    assert result.orders == 1  # good order processed
    assert result.skipped_orders == 1  # bad order skipped, not fatal
    assert result.new_entitlements == 6  # good order's items persisted (partial kept)


@pytest.mark.req("FRG-SRC-005")
async def test_401_midsync_expires_source_keeps_partial(db, config_dir):
    source = await _source(db)
    # First order returns comics; second returns 401 mid-sync.
    handler = order_handler(
        list_body=b'[{"gamekey":"good"},{"gamekey":"dead"}]',
        order_bodies={"good": fixture_bytes("order_comics.json")},
    )

    def routing(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/dead"):
            return httpx.Response(401, content=b"{}")
        return handler(request)

    factory = _factory(config_dir, routing)
    result = await _sync_one(db, factory, source, 0.0)

    assert result.expired is True
    # The source flipped to expired; partial results (the good order) are kept.
    refreshed = await get_source(db, source.id)
    assert refreshed.connection_state == "expired"
    assert len(await _entitlements(db)) == 6


@pytest.mark.req("FRG-SRC-005")
async def test_reconnect_resumes_from_expired(db, config_dir):
    source = await _source(db)
    # Drive it to expired first.
    async with db.write_session() as session:
        row = await session.get(SourceRow, source.id)
        row.connection_state = "expired"
    expired = await get_source(db, source.id)

    # Reconnect with a fresh cookie: live validation succeeds -> connected.
    factory = _factory(config_dir, order_handler(list_body=fixture_bytes("order_list.json")))
    row, order_count = await service_reconnect(
        db,
        factory,
        expired,
        settings=HumbleSettings(session_cookie="FRESH-COOKIE"),
        min_interval=0.0,
    )
    assert row.connection_state == "connected"
    assert order_count == 2

    # A subsequent sync now proceeds normally.
    sync_factory = _factory(config_dir, _one_order_handler())
    reloaded = await get_source(db, source.id)
    result = await run_sync(db, sync_factory, reloaded, min_interval=0.0)
    assert result.orders == 1
