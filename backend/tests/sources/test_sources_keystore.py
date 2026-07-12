"""Keystore decrypt-fail-soft for store sources (FRG-AUTH-012).

A source whose stored session cookie cannot be decrypted (the encryption key is
missing or changed) must degrade like an indexer/download-client: it is skipped
by sync (no batch abort, no retry storm, NOT flipped to ``expired``), surfaces a
credential-unavailable health warning, leaves the library/other sources
untouched, and clears the warning once the cookie is re-pasted (re-encrypted
under the current key).
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from cryptography.fernet import Fernet, MultiFernet

from foragerr import keystore as keystore_mod
from foragerr.health.service import HealthService
from foragerr.keystore import secret_state
from foragerr.sources import commands as source_commands
from foragerr.sources import ratelimit, repo
from foragerr.sources.commands import SourceSyncCommand, _handle_source_sync
from foragerr.sources.registry import TYPE_HUMBLE
from foragerr.sources.settings import HumbleSettings
from http_support import make_settings
from sources_support import fixture_bytes, make_factory, order_handler

GAMEKEY = "aBcD1234synthetic"


@pytest.fixture(autouse=True)
def _reset_gates():
    ratelimit.reset_gates()
    yield
    ratelimit.reset_gates()


def _install_wrong_key() -> None:
    """Swap in a keystore whose key cannot decrypt anything encrypted so far —
    the wrong-key boot (FRG-AUTH-012). ``available=False`` marks it a key change,
    so the health wording is 'encryption key missing or changed'."""
    wrong = keystore_mod.derive_fernet_key("a-different-passphrase", b"0123456789abcdef")
    keystore_mod.install_keystore(
        keystore_mod.Keystore(MultiFernet([Fernet(wrong)]), available=False)
    )


async def _source(db, name, cookie):
    return await repo.create_source(
        db,
        source_type=TYPE_HUMBLE,
        name=name,
        settings=HumbleSettings(session_cookie=cookie),
        connection_state="connected",
    )


@pytest.mark.req("FRG-AUTH-012")
async def test_wrong_key_degrades_only_that_source_batch_continues(
    db, config_dir, monkeypatch
):
    # Source A is encrypted under the ORIGINAL (correct) key.
    src_a = await _source(db, "A", "COOKIE-A")
    # After the key changes, A's cookie is undecryptable...
    _install_wrong_key()
    # ...but B, created now, is encrypted under the CURRENT key → decryptable.
    src_b = await _source(db, "B", "COOKIE-B")

    # Route B's sync at the committed fixtures, never the network.
    handler = order_handler(
        list_body=b'[{"gamekey":"%s"}]' % GAMEKEY.encode(),
        order_bodies={GAMEKEY: fixture_bytes("order_comics.json")},
    )
    factory = make_factory(config_dir, httpx.MockTransport(handler))
    monkeypatch.setattr(source_commands, "make_humble_factory", lambda s: factory)

    ctx = SimpleNamespace(
        db=db, settings=make_settings(config_dir), commands=None
    )
    summary = await _handle_source_sync(SourceSyncCommand(), ctx)

    # A is skipped (credential unavailable); B syncs — the batch is not aborted.
    assert "1 source(s) synced" in summary
    a = await repo.get_source(db, src_a.id)
    b = await repo.get_source(db, src_b.id)
    # A is NOT flipped to expired (a key problem, not cookie-expiry) and never
    # retried against — its last-sync metadata is untouched (no retry storm).
    assert a.connection_state == "connected"
    assert a.last_sync_at is None
    # B really synced.
    assert b.connection_state == "connected"
    assert b.last_sync_at is not None
    assert len(await repo.list_entitlements(db, src_b.id)) > 0
    assert await repo.list_entitlements(db, src_a.id) == []


@pytest.mark.req("FRG-AUTH-012")
async def test_health_surfaces_credential_unavailable_for_source(db, config_dir):
    await _source(db, "Humble", "COOKIE")
    _install_wrong_key()

    svc = HealthService(db, make_settings(config_dir))
    warnings = await svc.warnings()
    text = " ".join(
        f"{w.message} {w.remediation_hint or ''}" for w in warnings
    )
    assert "credential unavailable" in text
    assert "encryption key missing or changed" in text


@pytest.mark.req("FRG-AUTH-012")
async def test_reconnect_reencrypts_and_clears_the_warning(db, config_dir):
    src = await _source(db, "Humble", "COOKIE")
    _install_wrong_key()
    stranded = await repo.get_source(db, src.id)
    assert secret_state(stranded.settings) == "unavailable"

    # Re-pasting the cookie persists it re-encrypted under the CURRENT key (the
    # reconnect write path) → the source is decryptable again.
    await repo.update_source_settings(
        db,
        src.id,
        settings=HumbleSettings(session_cookie="FRESH-COOKIE"),
        connection_state="connected",
    )
    healed = await repo.get_source(db, src.id)
    assert secret_state(healed.settings) == "ok"

    svc = HealthService(db, make_settings(config_dir))
    warnings = await svc.warnings()
    assert not any("credential unavailable" in w.message for w in warnings)
