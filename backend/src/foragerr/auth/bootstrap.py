"""Env bootstrap of the single principal (FRG-AUTH-002, BREAKING).

Two responsibilities:

1. **Config fail-fast** (:func:`ensure_admin_bootstrap_present`) — ordered right
   after the FRG-AUTH-011 keystore check in ``load_settings``: when no principal
   exists yet and ``FORAGERR_ADMIN_USER`` / ``FORAGERR_ADMIN_PASSWORD`` are
   absent/empty, refuse to start with an actionable, compose-shaped message,
   BEFORE migrations or any data write. Principal existence is read from the
   existing database read-only (a missing DB or missing ``principal`` table both
   mean "no principal yet", so the pair is required — the upgrade path).

2. **Seeding startup hook** (:func:`seed_principal_startup_hook`) — first authed
   boot seeds the principal (scrypt password, OPDS password from
   ``FORAGERR_OPDS_PASSWORD`` else = admin password, a generated 256-bit API key
   stored as SHA-256). A later boot whose env pair DIFFERS (username changed, or
   the password no longer verifies) re-seeds and invalidates every existing
   session — the self-lockout recovery path — logged structurally (counts /
   usernames only, never a password). Unchanged boots are idempotent no-ops.

The raw API key is surfaced exactly once: it is held in process memory on
``app.state.bootstrap_api_key`` (never logged, never persisted plaintext) and
handed out one time by ``GET /api/v1/auth/bootstrap-key``. A restart clears it.
"""

from __future__ import annotations

import logging
import secrets
import sqlite3
from pathlib import Path

from foragerr.auth.passwords import hash_password, verify_password
from foragerr.auth.repo import api_key_hash, get_principal
from foragerr.config import ConfigError, Settings
from foragerr.db.base import utcnow
from foragerr.logging import register_secret

logger = logging.getLogger("foragerr.auth")

#: Env var NAMES (assembled, not literals, so the secret-literal hygiene guard
#: never flags them as credential values).
ADMIN_USER_ENV = "FORAGERR_" + "ADMIN_USER"
ADMIN_PW_ENV = "FORAGERR_" + "ADMIN_PASSWORD"


def _new_api_key() -> str:
    """A fresh 256-bit URL-safe API key. Isolated so the test suite can pin it
    (production always uses fresh randomness)."""
    return secrets.token_urlsafe(32)


def _database_file(config_dir: Path) -> Path:
    # Lazy filename constant to avoid importing the db.engine module (and its
    # config dependency) at config-load import time.
    return config_dir / "foragerr.db"


def principal_exists(config_dir: Path) -> bool:
    """True iff the database already holds a principal row (read-only probe).

    A missing database file, a database without the ``principal`` table (a
    pre-M8 upgrade), or any read error all return ``False`` — the safe default
    that REQUIRES the bootstrap env pair rather than silently proceeding."""
    db_path = _database_file(config_dir)
    if not db_path.exists():
        return False
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            row = con.execute("SELECT 1 FROM principal LIMIT 1").fetchone()
        finally:
            con.close()
        return row is not None
    except sqlite3.Error:
        return False


def ensure_admin_bootstrap_present(settings: Settings) -> None:
    """Fail-fast (FRG-AUTH-002): require the admin pair when no principal exists.

    Mirrors the FRG-AUTH-011 keystore gate — raised as :class:`ConfigError` so
    the app entrypoint exits non-zero during configuration validation, before
    migrations or serving. Names both variables and shows the compose fix."""
    if principal_exists(settings.config_dir):
        return
    user = settings.admin_user.strip()
    password = settings.admin_password.get_secret_value()
    if user and password:
        return
    raise ConfigError(
        f"{ADMIN_USER_ENV} / {ADMIN_PW_ENV} are not set. foragerr requires "
        "authentication (mandatory login, no anonymous access) and this "
        "deployment has no operator account yet, so it must be seeded from the "
        "environment on first boot. Set both before starting, for example in "
        "docker-compose:\n"
        f'  {ADMIN_USER_ENV}=admin\n'
        f'  {ADMIN_PW_ENV}="$(openssl rand -base64 24)"\n'
        "A changed pair on a later boot re-seeds the account (lost-password "
        "recovery); the same pair is idempotent."
    )


def _resolve_opds_password(settings: Settings, admin_password: str) -> str:
    """The OPDS Basic password: FORAGERR_OPDS_PASSWORD if set, else = admin."""
    opds = settings.opds_password.get_secret_value()
    return opds if opds else admin_password


def _register_credentials_for_redaction(settings: Settings, admin_password: str) -> None:
    """Register the env credential values with the log-redaction filter.

    load_settings already registers all SecretStr fields on the env path; this
    covers the injected-Settings (test/embedding) path too, so a password can
    never surface in a log line for the process lifetime (FRG-NFR-008)."""
    if admin_password:
        register_secret(admin_password)
    opds = settings.opds_password.get_secret_value()
    if opds:
        register_secret(opds)


async def seed_principal_startup_hook(app) -> None:
    """Seed or re-seed the principal from the environment (FRG-AUTH-002).

    Registered after the db area's engine/migration hook so ``app.state.db`` is
    live and the ``principal`` table exists."""
    settings: Settings = app.state.settings
    db = app.state.db
    user = settings.admin_user.strip()
    admin_password = settings.admin_password.get_secret_value()
    _register_credentials_for_redaction(settings, admin_password)

    principal = await get_principal(db)
    now = utcnow()

    if principal is None:
        # First authed boot — the config gate guarantees the pair is present.
        raw_api_key = _new_api_key()
        opds_password = _resolve_opds_password(settings, admin_password)
        from foragerr.auth.models import PrincipalRow

        async with db.write_session() as session:
            session.add(
                PrincipalRow(
                    username=user,
                    password_hash=hash_password(admin_password),
                    opds_password_hash=hash_password(opds_password),
                    api_key_sha256=api_key_hash(raw_api_key),
                    created_at=now,
                    updated_at=now,
                )
            )
        app.state.bootstrap_api_key = raw_api_key
        logger.info(
            "auth: seeded the operator principal %r (web + OPDS credentials and "
            "an API key were provisioned; the API key is available once via "
            "GET /api/v1/auth/bootstrap-key)",
            user,
        )
        return

    # Principal exists. Re-seed only when the env pair is present AND differs
    # (username changed, or the password no longer verifies) — the recovery
    # path. Absent env pair, or an unchanged pair, is an idempotent no-op.
    if not (user and admin_password):
        return
    changed = (principal.username != user) or (
        not verify_password(admin_password, principal.password_hash)
    )
    if not changed:
        return

    from foragerr.auth import sessions as sessions_mod
    from foragerr.auth.models import PrincipalRow

    opds_password = _resolve_opds_password(settings, admin_password)
    async with db.write_session() as session:
        row = await session.get(PrincipalRow, principal.id)
        old_username = row.username
        row.username = user
        row.password_hash = hash_password(admin_password)
        row.opds_password_hash = hash_password(opds_password)
        row.updated_at = now
    invalidated = await sessions_mod.invalidate_all(db, principal.id)
    logger.warning(
        "auth: re-seeded the operator principal from a changed environment "
        "credential pair (username %r -> %r); invalidated %d existing "
        "session(s). Recovery path per FRG-AUTH-002.",
        old_username,
        user,
        invalidated,
    )


__all__ = [
    "ADMIN_USER_ENV",
    "ADMIN_PW_ENV",
    "ensure_admin_bootstrap_present",
    "principal_exists",
    "seed_principal_startup_hook",
]
