"""Source persistence: cookie encrypted-at-rest, write-only, and the
connection lifecycle keeping synced data (FRG-SRC-001/002)."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from foragerr.keystore import ENC_PREFIX
from foragerr.sources.models import SourceEntitlementRow, SourceRow
from foragerr.sources.registry import TYPE_HUMBLE
from foragerr.sources.repo import (
    create_source,
    get_source,
    list_sources,
    load_source_settings,
    public_settings,
)
from foragerr.sources.service import disconnect_source
from foragerr.sources.settings import HumbleSettings

COOKIE = "SUPER-SECRET-COOKIE-VALUE-abc123"


async def _make_source(db, cookie: str = COOKIE) -> SourceRow:
    return await create_source(
        db,
        source_type=TYPE_HUMBLE,
        name="Humble Bundle",
        settings=HumbleSettings(session_cookie=cookie),
    )


@pytest.mark.req("FRG-SRC-002")
async def test_cookie_encrypted_at_rest(db):
    row = await _make_source(db)
    stored = await get_source(db, row.id)
    # The persisted settings JSON frames the cookie as enc:v1:… — no plaintext.
    assert ENC_PREFIX in stored.settings
    assert COOKIE not in stored.settings


@pytest.mark.req("FRG-SRC-002")
async def test_no_plaintext_cookie_bytes_anywhere_in_db(db):
    await _make_source(db)
    # Scan every text column of every row for the plaintext cookie.
    async with db.read_session() as session:
        rows = (await session.execute(select(SourceRow))).scalars().all()
        for row in rows:
            assert COOKIE not in (row.settings or "")


@pytest.mark.req("FRG-SRC-002")
async def test_cookie_round_trips_via_keystore(db):
    row = await _make_source(db)
    stored = await get_source(db, row.id)
    model = load_source_settings(stored.type, stored.settings)
    assert model.session_cookie.get_secret_value() == COOKIE


@pytest.mark.req("FRG-SRC-002")
async def test_public_settings_drop_cookie_write_only(db):
    model = HumbleSettings(session_cookie=COOKIE)
    public = public_settings(model)
    assert "session_cookie" not in public


@pytest.mark.req("FRG-SRC-001")
async def test_disconnect_keeps_entitlements_and_clears_credential(db):
    row = await _make_source(db)
    now = dt.datetime(2026, 7, 12, 12, 0, 0)
    async with db.write_session() as session:
        session.add(
            SourceEntitlementRow(
                source_id=row.id,
                gamekey="g1",
                machine_name="m1",
                human_name="Kept Comic",
                classification="comic",
                review_status="matched",
                formats_json="[]",
                created_at=now,
                updated_at=now,
            )
        )

    disconnected = await disconnect_source(db, row.id)
    assert disconnected.connection_state == "disconnected"
    assert ENC_PREFIX not in disconnected.settings  # credential deleted
    assert disconnected.settings == "{}"

    # The entitlement row survives disconnect untouched.
    async with db.read_session() as session:
        ents = (await session.execute(select(SourceEntitlementRow))).scalars().all()
    assert len(ents) == 1
    assert ents[0].human_name == "Kept Comic"
    assert ents[0].review_status == "matched"


@pytest.mark.req("FRG-SRC-001")
async def test_list_sources_orders_by_id(db):
    a = await _make_source(db, cookie="c-a")
    b = await _make_source(db, cookie="c-b")
    rows = await list_sources(db)
    assert [r.id for r in rows] == [a.id, b.id]
