"""At-rest secret keystore tests (FRG-AUTH-008/011/012/013).

Covers the keystore crypto engine (framing, round-trip, tamper detection,
wrong-key vs corruption), the mandatory-key boot gate, decrypt-fail-soft health
degradation + re-entry recovery, the eager plaintext migration, and the
baseline no-plaintext-at-rest + auto-coverage acceptance checks.
"""

from __future__ import annotations

import json
import os
import time

import pytest
from cryptography.fernet import Fernet, MultiFernet
from pydantic import BaseModel, SecretStr

from foragerr import logging as flog
from foragerr.config import ConfigError, Settings, load_settings
from foragerr.indexers.repo import (
    _decrypt_payload,
    create_indexer,
    list_indexers,
    load_indexers,
    serialize_settings,
    update_indexer,
)
from foragerr.indexers.settings import NewznabSettings
from foragerr.keystore import (
    ENC_PREFIX,
    Keystore,
    KeystoreDecryptError,
    KeystoreMetaRow,
    _is_top_level_secret,
    current_keystore,
    decrypt_secret,
    derive_fernet_key,
    encrypt_secret,
    init_keystore,
    install_keystore,
    is_ciphertext,
    keystore_startup_hook,
    migrate_plaintext_secrets,
    reset_keystore,
    secret_state,
    top_level_secret_field_names,
)


def _contains_secretstr(annotation) -> bool:
    """True iff ``SecretStr`` appears ANYWHERE in a type annotation — top-level,
    inside a Union/list/dict, or inside a nested ``BaseModel``. The tripwire below
    uses this to prove no registered settings model buries a secret where the
    top-level-only keystore helpers would silently store it as plaintext."""
    from typing import get_args, get_origin

    if annotation is SecretStr:
        return True
    if get_origin(annotation) is not None:
        return any(_contains_secretstr(arg) for arg in get_args(annotation))
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return any(
            _contains_secretstr(field.annotation)
            for field in annotation.model_fields.values()
        )
    return False


# --- FRG-AUTH-008: keystore crypto engine -----------------------------------


@pytest.mark.req("FRG-AUTH-008")
def test_encrypt_frames_and_round_trips():
    ks = current_keystore()
    enc = ks.encrypt("super-secret-value")
    assert enc.startswith(ENC_PREFIX)
    assert "super-secret-value" not in enc
    assert ks.decrypt(enc) == "super-secret-value"


@pytest.mark.req("FRG-AUTH-008")
def test_tampered_ciphertext_is_rejected_not_silently_decoded():
    ks = current_keystore()
    enc = ks.encrypt("authentic-payload")
    body = enc[len(ENC_PREFIX) :]
    # Flip a character in the middle of the token to break the HMAC.
    mid = len(body) // 2
    flipped = "A" if body[mid] != "A" else "B"
    tampered = ENC_PREFIX + body[:mid] + flipped + body[mid + 1 :]
    with pytest.raises(KeystoreDecryptError):
        ks.decrypt(tampered)


@pytest.mark.req("FRG-AUTH-008")
def test_legacy_plaintext_passes_through_decrypt():
    # A value without the enc:v1 frame is returned unchanged (partial migration).
    assert current_keystore().decrypt("plain-legacy-value") == "plain-legacy-value"
    assert decrypt_secret("plain-legacy-value") == "plain-legacy-value"
    assert not is_ciphertext("plain-legacy-value")


@pytest.mark.req("FRG-AUTH-008")
def test_empty_secret_is_not_encrypted():
    # Nothing to protect: an empty secret stays empty (never framed).
    assert encrypt_secret("") == ""


@pytest.mark.req("FRG-AUTH-008")
def test_auto_coverage_new_secretstr_field_round_trips_with_no_provider_code():
    """A brand-new settings model with a fresh SecretStr field is encrypted at
    rest by the generic serialize/deserialize helpers — no keystore- or
    provider-specific code (single source of truth = the SecretStr annotation)."""

    class SyntheticSourceSettings(BaseModel):
        host: str
        session_cookie: SecretStr  # a field name the keystore has never seen

    model = SyntheticSourceSettings(
        host="store.example", session_cookie=SecretStr("brand-new-session-token")
    )
    serialized = serialize_settings(model)
    assert "brand-new-session-token" not in serialized
    assert ENC_PREFIX in serialized
    # Non-secret fields are untouched.
    payload = json.loads(serialized)
    assert payload["host"] == "store.example"
    assert is_ciphertext(payload["session_cookie"])
    # Round-trips back to plaintext with the generic decrypt helper.
    decrypted = _decrypt_payload(payload)
    assert decrypted["session_cookie"] == "brand-new-session-token"


@pytest.mark.req("FRG-AUTH-008")
def test_scrypt_derivation_is_deterministic_and_salt_sensitive():
    salt_a = os.urandom(16)
    salt_b = os.urandom(16)
    assert derive_fernet_key("pass", salt_a) == derive_fernet_key("pass", salt_a)
    assert derive_fernet_key("pass", salt_a) != derive_fernet_key("pass", salt_b)
    assert derive_fernet_key("pass", salt_a) != derive_fernet_key("other", salt_a)


@pytest.mark.req("FRG-AUTH-008")
def test_scrypt_boot_latency_within_budget():
    """The real (n=2**15) scrypt derivation runs once at boot; it must stay well
    within the FRG-NFR-001 startup budget. Measured here at the production cost
    (the suite otherwise runs a cheap cost) — see design.md rollback/latency
    note for the recorded figure."""
    salt = os.urandom(16)
    start = time.monotonic()
    derive_fernet_key("a-representative-passphrase", salt, n=2**15)
    elapsed = time.monotonic() - start
    # Generous ceiling to avoid CI flakiness; the real figure is ~tens of ms.
    assert elapsed < 2.0, f"scrypt derivation took {elapsed:.3f}s (budget 2.0s)"


# --- FRG-AUTH-008: baseline acceptance (no plaintext at rest) ----------------


async def _new_indexer(db, *, api_key: str, name: str = "DogNZB"):
    return await create_indexer(
        db,
        name=name,
        implementation="newznab",
        settings=NewznabSettings(base_url="https://idx.test", api_key=api_key),
    )


@pytest.mark.req("FRG-AUTH-008")
async def test_no_plaintext_secret_in_db_or_backup(db, tmp_path):
    from foragerr.db.backup import write_consistent_backup

    secret = "dog-plaintext-key-should-never-hit-disk"
    await init_and_install(db)
    await _new_indexer(db, api_key=secret)

    # Force a WAL checkpoint so the settings row is in the main db file, then a
    # consistent backup (the "backup cycle").
    db_path = db.db_path
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()

    backup_dir = tmp_path / "bkp"
    backup_dir.mkdir()
    write_consistent_backup(db_path, backup_dir)

    needle = secret.encode()
    # No plaintext (or its bytes) in the live db, its sidecars, or the backup.
    for path in list(db_path.parent.glob("foragerr.db*")) + list(
        backup_dir.rglob("*")
    ):
        if path.is_file():
            assert needle not in path.read_bytes(), f"plaintext secret found in {path}"

    # The settings column carries the enc:v1 frame, and the only keystore
    # artifacts on disk are the non-secret salt + sentinel.
    rows = await list_indexers(db)
    stored = json.loads(rows[0].settings)
    assert is_ciphertext(stored["api_key"])
    async with db.read_session() as session:
        meta = await session.get(KeystoreMetaRow, 1)
        assert meta is not None and meta.salt and meta.sentinel
    # The passphrase itself appears in no on-disk file.
    for path in db_path.parent.rglob("*"):
        if path.is_file():
            assert b"test-secret-passphrase" not in path.read_bytes()


# --- FRG-AUTH-011: mandatory environment key at startup ----------------------


@pytest.mark.req("FRG-AUTH-011")
def test_missing_key_blocks_startup(config_dir, monkeypatch):
    monkeypatch.delenv("FORAGERR_SECRET_KEY", raising=False)
    with pytest.raises(ConfigError) as exc:
        load_settings()
    message = str(exc.value)
    assert "FORAGERR_SECRET_KEY" in message
    assert "passphrase" in message.lower()
    assert "openssl" in message  # shows how to set it


@pytest.mark.req("FRG-AUTH-011")
def test_empty_key_blocks_startup(config_dir, monkeypatch):
    monkeypatch.setenv("FORAGERR_SECRET_KEY", "")
    with pytest.raises(ConfigError) as exc:
        load_settings()
    assert "FORAGERR_SECRET_KEY" in str(exc.value)


@pytest.mark.req("FRG-AUTH-011")
def test_present_key_proceeds_and_is_redaction_registered(config_dir, monkeypatch):
    flog.clear_secrets()
    monkeypatch.setenv("FORAGERR_SECRET_KEY", "a-real-operator-passphrase")
    settings = load_settings()
    assert settings.secret_key.get_secret_value() == "a-real-operator-passphrase"
    # The passphrase self-registered with the log-redaction filter (FRG-NFR-008).
    assert flog.redact("key=a-real-operator-passphrase x") != (
        "key=a-real-operator-passphrase x"
    )


# --- FRG-AUTH-012: decrypt failure degrades the integration, not the service --


async def init_and_install(db, passphrase: str = "test-secret-passphrase") -> Keystore:
    ks = await init_keystore(db, passphrase)
    install_keystore(ks)
    return ks


async def _health_warnings(db):
    from foragerr.health.service import HealthService

    service = HealthService(db, Settings(config_dir=db.db_path.parent))
    return await service.warnings()


@pytest.mark.req("FRG-AUTH-012")
async def test_wrong_key_boot_degrades_only_the_integration(db, tmp_path):
    # Encrypt a provider secret under passphrase A (a real keystore_meta row).
    await init_and_install(db, "passphrase-A")
    await _new_indexer(db, api_key="key-under-A", name="DogNZB")

    # Re-boot with a different passphrase B: the sentinel no longer matches.
    reset_keystore()
    ks_b = await init_and_install(db, "passphrase-B")
    assert ks_b.available is False  # sentinel mismatch detected

    # The affected indexer is isolated (no retry storm) rather than searched.
    listing = await load_indexers(db)
    assert [r.name for r in listing.failed] == ["DogNZB"]
    assert listing.healthy == []

    # Health surfaces exactly one credential-unavailable warning naming the key.
    warnings = await _health_warnings(db)
    cred = [w for w in warnings if "credential unavailable" in w.message]
    assert len(cred) == 1
    assert "encryption key missing or changed" in cred[0].message
    assert "re-enter" in cred[0].message.lower()

    # Library/OPDS unaffected: a library read still works, and the database
    # health component is not in error because of the key mismatch.
    from foragerr.library import repo as library_repo

    async with db.read_session() as session:
        await library_repo.list_series(session)  # does not raise


@pytest.mark.req("FRG-AUTH-012")
async def test_reentry_reencrypts_under_current_key_and_clears_warning(db):
    await init_and_install(db, "passphrase-A")
    row = await _new_indexer(db, api_key="key-under-A")

    reset_keystore()
    await init_and_install(db, "passphrase-B")  # wrong key: row now unreadable
    assert secret_state((await load_indexers(db)).failed[0].settings) == "unavailable"

    # Operator re-enters the secret through the ordinary edit path: it is
    # re-encrypted under the CURRENT key (B), clearing the condition.
    await update_indexer(
        db,
        row.id,
        settings=NewznabSettings(base_url="https://idx.test", api_key="key-under-B"),
    )
    listing = await load_indexers(db)
    assert [r.name for r in listing.healthy] == ["DogNZB"]
    assert listing.failed == []
    warnings = await _health_warnings(db)
    assert not [w for w in warnings if "credential unavailable" in w.message]


@pytest.mark.req("FRG-AUTH-012")
async def test_right_key_corrupt_row_is_distinguished_from_key_mismatch(db):
    ks = await init_and_install(db, "passphrase-A")
    row = await _new_indexer(db, api_key="genuine-key")
    assert ks.available is True

    # Corrupt just this row's ciphertext (right key, tampered value).
    async with db.write_session() as session:
        stored = await session.get(type(row), row.id)
        payload = json.loads(stored.settings)
        token = payload["api_key"][len(ENC_PREFIX) :]
        mid = len(token) // 2
        payload["api_key"] = ENC_PREFIX + token[:mid] + (
            "A" if token[mid] != "A" else "B"
        ) + token[mid + 1 :]
        stored.settings = json.dumps(payload, sort_keys=True)

    warnings = await _health_warnings(db)
    cred = [w for w in warnings if "credential unavailable" in w.message]
    assert len(cred) == 1
    # Sentinel still matches ⇒ message says corrupt/unreadable, not key-changed.
    assert "corrupt" in cred[0].message.lower()


# --- FRG-AUTH-013: plaintext secret migration on first keyed boot ------------


async def _make_plaintext_indexer(db, api_key: str, name: str = "Legacy") -> int:
    """Create a row then rewrite its settings column to legacy PLAINTEXT."""
    row = await _new_indexer(db, api_key="temp", name=name)
    async with db.write_session() as session:
        stored = await session.get(type(row), row.id)
        payload = json.loads(stored.settings)
        payload["api_key"] = api_key  # plaintext, no enc:v1 frame
        stored.settings = json.dumps(payload, sort_keys=True)
    return row.id


@pytest.mark.req("FRG-AUTH-013")
async def test_upgrade_migrates_plaintext_secrets_once(db):
    await init_and_install(db)
    rid = await _make_plaintext_indexer(db, "legacy-plaintext-key")

    migrated = await migrate_plaintext_secrets(db)
    assert migrated == 1

    async with db.read_session() as session:
        from foragerr.indexers.models import IndexerRow

        stored = json.loads((await session.get(IndexerRow, rid)).settings)
    assert is_ciphertext(stored["api_key"])
    assert decrypt_secret(stored["api_key"]) == "legacy-plaintext-key"

    # Idempotent: a second pass migrates nothing.
    assert await migrate_plaintext_secrets(db) == 0


@pytest.mark.req("FRG-AUTH-013")
async def test_restored_plaintext_backup_is_remigrated(db):
    await init_and_install(db)
    await _make_plaintext_indexer(db, "first-legacy-key", name="First")
    assert await migrate_plaintext_secrets(db) == 1
    assert await migrate_plaintext_secrets(db) == 0

    # A pre-upgrade backup is restored, reintroducing a plaintext row alongside
    # the already-encrypted one: the same idempotent pass re-encrypts only it.
    await _make_plaintext_indexer(db, "restored-legacy-key", name="Restored")
    assert await migrate_plaintext_secrets(db) == 1

    healthy = await list_indexers(db)
    keys = sorted(
        decrypt_secret(json.loads(r.settings)["api_key"]) for r in healthy
    )
    assert keys == ["first-legacy-key", "restored-legacy-key"]


@pytest.mark.req("FRG-AUTH-013")
async def test_wrong_key_boot_defers_plaintext_migration(db, monkeypatch):
    """A wrong-key boot must NOT migrate legacy plaintext: encrypting it under the
    mismatched key would strand it forever from the correct key. The row is left
    untouched; a later correct-key boot migrates it."""
    from types import SimpleNamespace

    from foragerr.indexers.models import IndexerRow

    # Establish the keystore under passphrase A and inject a legacy PLAINTEXT row.
    await init_and_install(db, "passphrase-A")
    rid = await _make_plaintext_indexer(db, "legacy-plaintext-key")

    # Boot the real startup hook with the WRONG passphrase B (sentinel mismatch).
    reset_keystore()
    monkeypatch.setenv("FORAGERR_SECRET_KEY", "passphrase-B")
    settings_b = Settings(config_dir=db.db_path.parent)
    assert settings_b.secret_key.get_secret_value() == "passphrase-B"
    await keystore_startup_hook(
        SimpleNamespace(state=SimpleNamespace(settings=settings_b, db=db))
    )
    assert current_keystore().available is False

    # The plaintext row is untouched — never encrypted under the wrong key.
    async with db.read_session() as session:
        stored = json.loads((await session.get(IndexerRow, rid)).settings)
    assert stored["api_key"] == "legacy-plaintext-key"
    assert not is_ciphertext(stored["api_key"])

    # A subsequent correct-key (A) boot migrates it.
    reset_keystore()
    monkeypatch.setenv("FORAGERR_SECRET_KEY", "passphrase-A")
    settings_a = Settings(config_dir=db.db_path.parent)
    await keystore_startup_hook(
        SimpleNamespace(state=SimpleNamespace(settings=settings_a, db=db))
    )
    assert current_keystore().available is True
    async with db.read_session() as session:
        stored = json.loads((await session.get(IndexerRow, rid)).settings)
    assert is_ciphertext(stored["api_key"])
    assert decrypt_secret(stored["api_key"]) == "legacy-plaintext-key"


@pytest.mark.req("FRG-AUTH-012")
async def test_lost_keystore_meta_over_ciphertext_reports_key_missing(db, caplog):
    """A lost keystore_meta row while enc:v1: secrets survive re-inits a fresh
    keystore (available), but the previous key is unrecoverable: a prominent
    WARNING is logged, health uses the key-missing/changed wording (not corrupt
    row), and re-entry under the new key clears it (FRG-AUTH-012)."""
    import logging as _logging

    from foragerr.indexers.models import IndexerRow

    # A secret encrypted under passphrase A with a real keystore_meta row.
    await init_and_install(db, "passphrase-A")
    row = await _new_indexer(db, api_key="key-under-A", name="DogNZB")

    # The keystore_meta row is lost, but the ciphertext remains in the settings.
    async with db.write_session() as session:
        meta = await session.get(KeystoreMetaRow, 1)
        await session.delete(meta)

    reset_keystore()
    with caplog.at_level(_logging.WARNING, logger="foragerr.keystore"):
        ks = await init_keystore(db, "passphrase-B")  # meta gone → fresh keystore
    install_keystore(ks)
    assert ks.available is True
    assert ks.reinitialized_over_ciphertext is True
    assert any("unrecoverable" in rec.message for rec in caplog.records)

    # The stranded ciphertext is unreadable under the new key; health says the key
    # is missing/changed (the original key is gone), not "corrupt row".
    async with db.read_session() as session:
        stored = json.loads((await session.get(IndexerRow, row.id)).settings)
    assert secret_state(json.dumps(stored)) == "unavailable"
    warnings = await _health_warnings(db)
    cred = [w for w in warnings if "credential unavailable" in w.message]
    assert len(cred) == 1
    assert "encryption key missing or changed" in cred[0].message
    assert "corrupt" not in cred[0].message.lower()

    # Re-entry under the CURRENT (new) key clears the condition.
    await update_indexer(
        db,
        row.id,
        settings=NewznabSettings(base_url="https://idx.test", api_key="key-under-B"),
    )
    listing = await load_indexers(db)
    assert [r.name for r in listing.healthy] == ["DogNZB"]
    warnings = await _health_warnings(db)
    assert not [w for w in warnings if "credential unavailable" in w.message]


# --- FRG-AUTH-011: injected-Settings key gate (create_app) -------------------


@pytest.mark.req("FRG-AUTH-011")
def test_create_app_enforces_key_gate_on_injected_settings(tmp_path, monkeypatch):
    """create_app(settings=...) bypasses load_settings' FRG-AUTH-011 gate; the gate
    is factored so create_app enforces it too — a keyless injected Settings raises
    the same typed ConfigError."""
    from foragerr.app import create_app

    monkeypatch.delenv("FORAGERR_SECRET_KEY", raising=False)
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    keyless = Settings(config_dir=cfg)
    assert not keyless.secret_key.get_secret_value().strip()
    with pytest.raises(ConfigError) as exc:
        create_app(keyless)
    assert "FORAGERR_SECRET_KEY" in str(exc.value)


# --- FRG-AUTH-008: top-level-only secret detection tripwire ------------------


@pytest.mark.req("FRG-AUTH-008")
def test_no_registered_settings_model_hides_a_nested_secret():
    """Secret detection + encryption is TOP-LEVEL only (serialize_settings /
    _decrypt_payload / register_row_secrets / the boot migration). A SecretStr
    buried inside a list, dict, or nested BaseModel would be stored as PLAINTEXT.
    Fail loudly here so a future author extends ALL of those helpers (and
    top_level_secret_field_names) before shipping such a field."""
    import foragerr.ddl  # noqa: F401 — registers the getcomics indexer implementation
    from foragerr.downloads.registry import implementations as dc_impls
    from foragerr.indexers.registry import implementations as idx_impls
    from foragerr.sources.registry import implementations as src_impls

    models = [impl.settings_model for impl in idx_impls()]
    models += [impl.settings_model for impl in dc_impls()]
    models += [impl.settings_model for impl in src_impls()]
    for model_cls in models:
        for name, field in model_cls.model_fields.items():
            if _is_top_level_secret(field.annotation):
                continue  # a plain top-level SecretStr is handled correctly
            assert not _contains_secretstr(field.annotation), (
                f"{model_cls.__name__}.{name} buries a SecretStr inside a "
                "container/sub-model; the top-level-only keystore helpers would "
                "store it as PLAINTEXT. Extend serialize_settings/_decrypt_payload/"
                "register_row_secrets/the boot migration before shipping this field."
            )


@pytest.mark.req("FRG-AUTH-008")
def test_getcomics_settings_carries_no_secret():
    """ddl/search_provider.py + ddl/queue.py load GetComicsSettings WITHOUT the
    keystore-decrypting loader; that bypass is safe ONLY while the model carries no
    SecretStr. Pin it so the bypass can never be tripped silently."""
    from foragerr.ddl.settings import GetComicsSettings

    assert not top_level_secret_field_names(GetComicsSettings)
    assert all(
        not _contains_secretstr(field.annotation)
        for field in GetComicsSettings.model_fields.values()
    )
