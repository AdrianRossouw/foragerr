"""At-rest secret encryption keystore (FRG-AUTH-008/011/012/013).

UI-entered provider secrets (``SecretStr`` fields in indexer / download-client
``settings`` JSON) are stored encrypted with authenticated encryption (Fernet:
AES-128-CBC + HMAC-SHA256), never in plaintext (RISK-041). The Fernet key is
DERIVED from the operator-chosen ``FORAGERR_SECRET_KEY`` passphrase via scrypt
with a random per-deployment salt; the salt and a sentinel check-value live in
the single-row ``keystore_meta`` table (both non-secret). The passphrase itself
is supplied through the environment ONLY and never written to ``/config``.

Design mechanics (m6-keystore, owner decisions 2026-07-10/11):

- **Derivation** — ``scrypt(passphrase, salt, n=2**15, r=8, p=1) -> 32 bytes``
  → urlsafe-base64 → Fernet key. scrypt's memory/CPU cost makes offline
  brute-force of a stolen backup expensive (the threat is "backup file without
  the deployment env").
- **Cipher** — ``MultiFernet([Fernet(key)])`` from day one, so the M8 key
  rotation only prepends a new key + ``rotate()``s rows — no storage-format
  change.
- **Storage format** — ``enc:v1:<fernet-token>`` in-place inside the existing
  settings JSON string values. The ``enc:v1:`` prefix is unambiguous (legacy
  plaintext never carries it) and versions the format.
- **Sentinel** — a fixed plaintext encrypted at keystore init. On boot a
  successful sentinel decrypt proves the passphrase matches the one that
  created the keystore; failure means the key changed (drives FRG-AUTH-012
  health messaging and distinguishes a wrong key from a single corrupt row,
  which Fernet's HMAC also catches).
- **Fail-soft** (FRG-AUTH-012) — encryption always uses the currently derived
  key, so saving a secret always works. Only DECRYPTING data written under a
  different key fails; such a row is reported credential-unavailable for its
  owning integration and behaves as unconfigured, never crashing startup or the
  library/OPDS surfaces.
- **Migration** (FRG-AUTH-013) — :func:`migrate_plaintext_secrets` converts any
  pre-existing plaintext secret to ``enc:v1:`` at first keyed boot, idempotently
  (prefix check), covering both a fresh upgrade and a restored plaintext backup.

Secret-field detection is the single source of truth already used elsewhere:
values are secret iff their settings-model field is annotated ``SecretStr``, so
a future persisted secret is encrypted with zero keystore-specific code in the
new provider.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import threading

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from pydantic import SecretStr
from sqlalchemy import LargeBinary, Text
from sqlalchemy.orm import Mapped, mapped_column

from foragerr.db.base import Base, StrictDateTime, StrictInteger, utcnow

logger = logging.getLogger("foragerr.keystore")

#: The ciphertext framing: ``enc:v1:<urlsafe-b64 fernet token>``.
ENC_PREFIX = "enc:v1:"

#: scrypt cost parameters. n=2**15 (32768), r=8, p=1 is the interactive-hardened
#: profile: ~32 MiB memory and ~tens of ms on the target hardware — expensive
#: enough to blunt offline brute-force of a stolen backup, cheap enough to run
#: once at boot within the FRG-NFR-001 startup budget. Module-level so the test
#: suite can lower ``SCRYPT_N`` for speed (production always uses the default).
SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
SALT_BYTES = 16

#: Fixed plaintext encrypted at keystore init as the sentinel check-value.
_SENTINEL_PLAINTEXT = b"foragerr-keystore-sentinel-v1"


class KeystoreError(RuntimeError):
    """A keystore operation failed."""


class KeystoreNotReady(KeystoreError):
    """No keystore has been installed for this process yet."""


class KeystoreDecryptError(KeystoreError):
    """A specific ciphertext value could not be decrypted (wrong key/corrupt)."""


class KeystoreMetaRow(Base):
    """The single ``keystore_meta`` row (id=1): salt + sentinel (created 0019).

    Both columns are non-secret: the salt only prevents rainbow precomputation,
    and the sentinel is a fixed plaintext encrypted under the derived key. The
    passphrase is never stored here (or anywhere on disk)."""

    __tablename__ = "keystore_meta"

    id: Mapped[int] = mapped_column(StrictInteger, primary_key=True)
    salt: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sentinel: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[object] = mapped_column(StrictDateTime, nullable=False)


def _new_salt() -> bytes:
    """A fresh random keystore salt. Isolated so tests can pin it."""
    return os.urandom(SALT_BYTES)


def derive_fernet_key(passphrase: str, salt: bytes, *, n: int | None = None) -> bytes:
    """Derive a urlsafe-base64 Fernet key from ``passphrase`` + ``salt`` via scrypt.

    ``n`` overrides the module ``SCRYPT_N`` cost (production passes ``None`` ⇒ the
    default; the latency check pins the real value regardless of test tuning)."""
    kdf = Scrypt(
        salt=salt,
        length=SCRYPT_DKLEN,
        n=SCRYPT_N if n is None else n,
        r=SCRYPT_R,
        p=SCRYPT_P,
    )
    raw = kdf.derive(passphrase.encode("utf-8"))
    return base64.urlsafe_b64encode(raw)


def is_ciphertext(value: object) -> bool:
    """True iff ``value`` is an ``enc:v1:`` framed ciphertext string."""
    return isinstance(value, str) and value.startswith(ENC_PREFIX)


class Keystore:
    """The process keystore: encrypt/decrypt ``enc:v1:`` secret values.

    ``available`` records whether the boot sentinel decrypted (i.e. the supplied
    passphrase matches the one that established the keystore). Encryption always
    works — it uses the currently derived key — so a mismatched key only affects
    decryption of data written under the original key (FRG-AUTH-012 fail-soft)."""

    def __init__(self, fernet: MultiFernet, *, available: bool) -> None:
        self._fernet = fernet
        self._available = available

    @property
    def available(self) -> bool:
        """Whether the boot sentinel matched (passphrase unchanged)."""
        return self._available

    def encrypt(self, plaintext: str) -> str:
        """Encrypt ``plaintext`` to an ``enc:v1:<token>`` value (current key)."""
        token = self._fernet.encrypt(plaintext.encode("utf-8"))
        return ENC_PREFIX + token.decode("ascii")

    def decrypt(self, value: str) -> str:
        """Decrypt an ``enc:v1:<token>`` value; raise on wrong-key/corrupt.

        A value without the prefix is returned unchanged (legacy plaintext), so
        a partially-migrated row is tolerated."""
        if not is_ciphertext(value):
            return value
        token = value[len(ENC_PREFIX) :].encode("ascii")
        try:
            return self._fernet.decrypt(token).decode("utf-8")
        except (InvalidToken, ValueError) as exc:
            raise KeystoreDecryptError(
                "stored secret could not be decrypted (encryption key missing or "
                "changed, or the value is corrupt)"
            ) from exc


# --- process-global keystore holder -----------------------------------------
# Module-global by design (mirrors logging._SECRETS / metadata.ratelimit): the
# repo (de)serialization helpers are plain functions called from many call
# sites without a keystore parameter, so one process-wide keystore is the single
# place every persisted secret flows through.

_lock = threading.Lock()
_keystore: Keystore | None = None


def install_keystore(keystore: Keystore) -> None:
    """Install the process keystore (called once at boot)."""
    global _keystore
    with _lock:
        _keystore = keystore


def current_keystore() -> Keystore | None:
    """The installed process keystore, or ``None`` before boot / in a unit test."""
    with _lock:
        return _keystore


def reset_keystore() -> None:
    """Forget the installed keystore — TEST-ONLY isolation hook."""
    global _keystore
    with _lock:
        _keystore = None


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a non-empty secret to ``enc:v1:``; raise if no keystore installed.

    An empty string is returned unchanged (nothing to protect)."""
    if not plaintext:
        return plaintext
    ks = current_keystore()
    if ks is None:
        raise KeystoreNotReady(
            "keystore is not initialized; cannot encrypt a secret at rest"
        )
    if is_ciphertext(plaintext):
        return plaintext  # already framed — never double-encrypt
    return ks.encrypt(plaintext)


def decrypt_secret(value: str) -> str:
    """Decrypt an ``enc:v1:`` value; plaintext/legacy values pass through.

    Raises :class:`KeystoreDecryptError` when a framed value cannot be decrypted
    (wrong key / corrupt). Non-framed values are returned unchanged even when no
    keystore is installed, so legacy plaintext and unit tests keep working."""
    if not is_ciphertext(value):
        return value
    ks = current_keystore()
    if ks is None:
        raise KeystoreNotReady(
            "keystore is not initialized; cannot decrypt a stored secret"
        )
    return ks.decrypt(value)


def secret_state(settings_json: str) -> str:
    """Classify a settings row's stored secrets: ``"ok"`` or ``"unavailable"``.

    ``"unavailable"`` iff the row carries at least one ``enc:v1:`` value that the
    current keystore cannot decrypt (wrong key / corrupt) — the FRG-AUTH-012
    credential-unavailable signal the health service surfaces. A row with no
    framed secrets, unparseable JSON, or no installed keystore is ``"ok"`` (not
    this check's concern)."""
    ks = current_keystore()
    if ks is None:
        return "ok"
    try:
        payload = json.loads(settings_json)
    except (ValueError, TypeError):
        return "ok"
    if not isinstance(payload, dict):
        return "ok"
    for value in payload.values():
        if is_ciphertext(value):
            try:
                ks.decrypt(value)
            except KeystoreDecryptError:
                return "unavailable"
    return "ok"


# --- boot: keystore init + eager plaintext migration ------------------------


async def init_keystore(db, passphrase: str) -> Keystore:
    """Load or create the keystore for this database and return it (not installed).

    Fresh database (no ``keystore_meta`` row): generate a salt, derive the key,
    encrypt + persist the sentinel, and return an available keystore. Existing
    row: derive from the stored salt and probe the sentinel — a decrypt success
    marks the keystore available; a failure marks it unavailable and logs an
    actionable warning (FRG-AUTH-012 wrong-key boot), never raising."""
    async with db.read_session() as session:
        row = await session.get(KeystoreMetaRow, 1)
        if row is not None:
            session.expunge(row)

    if row is None:
        salt = _new_salt()
        fernet = MultiFernet([Fernet(derive_fernet_key(passphrase, salt))])
        sentinel = fernet.encrypt(_SENTINEL_PLAINTEXT).decode("ascii")
        async with db.write_session() as session:
            session.add(
                KeystoreMetaRow(
                    id=1, salt=salt, sentinel=sentinel, created_at=utcnow()
                )
            )
        logger.info("keystore: initialized a new keystore (salt + sentinel persisted)")
        return Keystore(fernet, available=True)

    fernet = MultiFernet([Fernet(derive_fernet_key(passphrase, row.salt))])
    try:
        fernet.decrypt(row.sentinel.encode("ascii"))
        available = True
    except (InvalidToken, ValueError):
        available = False
        logger.warning(
            "keystore: FORAGERR_SECRET_KEY does not match the stored keystore "
            "sentinel; existing encrypted credentials cannot be decrypted until "
            "the original passphrase is restored or the affected secrets are "
            "re-entered. Startup and the library/OPDS surfaces are unaffected."
        )
    return Keystore(fernet, available=available)


async def migrate_plaintext_secrets(db) -> int:
    """Encrypt any pre-keystore plaintext secret to ``enc:v1:`` (FRG-AUTH-013).

    Idempotent: a value already carrying the prefix is skipped, so this is a
    no-op on an already-migrated database and re-encrypts only the plaintext rows
    a restored pre-upgrade backup reintroduces. Secret fields are identified by
    their ``SecretStr`` annotation (the single source of truth). Returns the
    count of migrated values; logs the count only, never a value. A row whose
    settings JSON cannot be validated is left untouched (it surfaces as a failed
    provider row elsewhere) — one bad row never aborts the pass."""
    from foragerr.downloads.models import DownloadClientRow
    from foragerr.downloads.registry import (
        validate_settings as validate_client_settings,
    )
    from foragerr.indexers.models import IndexerRow
    from foragerr.indexers.registry import validate_settings as validate_indexer_settings

    migrated = 0
    for model_cls, validate in (
        (IndexerRow, validate_indexer_settings),
        (DownloadClientRow, validate_client_settings),
    ):
        migrated += await _migrate_table(db, model_cls, validate)
    return migrated


async def _migrate_table(db, model_cls, validate) -> int:
    from sqlalchemy import select

    async with db.write_session() as session:
        rows = (await session.execute(select(model_cls))).scalars().all()
        migrated = 0
        for row in rows:
            try:
                payload = json.loads(row.settings)
            except (ValueError, TypeError):
                continue
            if not isinstance(payload, dict):
                continue
            try:
                model = validate(row.implementation, payload)
            except Exception:  # noqa: BLE001 — a corrupt row is isolated, not fatal
                continue
            secret_names = [
                name
                for name in type(model).model_fields
                if isinstance(getattr(model, name), SecretStr)
            ]
            changed = False
            for name in secret_names:
                value = payload.get(name)
                if isinstance(value, str) and value and not is_ciphertext(value):
                    payload[name] = encrypt_secret(value)
                    changed = True
            if changed:
                row.settings = json.dumps(payload, sort_keys=True)
                migrated += 1
        return migrated


async def keystore_startup_hook(app) -> None:
    """Startup hook: derive/init the keystore, install it, migrate plaintext.

    Registered in ``create_app`` right after the db area's migration/engine
    startup hook (so ``keystore_meta`` exists and ``app.state.db`` is live) and
    before the first-run seed / any secret persistence. The ``FORAGERR_SECRET_KEY``
    presence gate already ran at config load (FRG-AUTH-011), so the passphrase is
    guaranteed non-empty here."""
    settings = app.state.settings
    passphrase = settings.secret_key.get_secret_value()
    db = app.state.db
    keystore = await init_keystore(db, passphrase)
    install_keystore(keystore)
    migrated = await migrate_plaintext_secrets(db)
    if migrated:
        logger.info(
            "keystore: encrypted %d pre-existing plaintext secret value(s) at boot",
            migrated,
        )


__all__ = [
    "ENC_PREFIX",
    "Keystore",
    "KeystoreDecryptError",
    "KeystoreError",
    "KeystoreMetaRow",
    "KeystoreNotReady",
    "current_keystore",
    "decrypt_secret",
    "derive_fernet_key",
    "encrypt_secret",
    "init_keystore",
    "install_keystore",
    "is_ciphertext",
    "keystore_startup_hook",
    "migrate_plaintext_secrets",
    "reset_keystore",
    "secret_state",
]
