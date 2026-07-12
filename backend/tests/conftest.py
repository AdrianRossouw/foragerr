"""Shared fixtures: env/log isolation for the foundation test suite."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Literal, Optional

import pytest

from foragerr import logging as flog


#: The mandatory at-rest passphrase every test boots with (FRG-AUTH-011).
TEST_SECRET_KEY = "test-secret-passphrase"

#: The bootstrap operator credentials every test boots with (FRG-AUTH-002). Any
#: ``create_app`` boot seeds this principal; tests exercising the fail-fast /
#: re-seed paths delenv or override these.
TEST_ADMIN_USER = "admin"
TEST_ADMIN_PASSWORD = "test-admin-password"

#: The API key every seeded principal gets under test (the bootstrap key
#: generator is pinned to this), so the auto-auth client authenticates even when
#: an app boots over a principal seeded on a previous boot (no new key minted).
TEST_API_KEY = "test-bootstrap-api-key-0123456789ABCDEF"


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Strip FORAGERR_* env vars and reset redaction/handler + keystore state.

    Installs a deterministic, cheap process keystore (m6-keystore): scrypt cost
    is lowered and the salt pinned so it is fast AND matches whatever an
    app-boot's ``init_keystore`` derives from the SAME passphrase + salt — so a
    secret encrypted before a ``create_app`` boot still decrypts after it. The
    mandatory ``FORAGERR_SECRET_KEY`` is set so any ``load_settings`` boot passes
    the FRG-AUTH-011 gate (tests exercising the missing-key path delenv it).

    The mandatory login bootstrap env pair (FRG-AUTH-002) is set too, and the
    auth password KDF cost is lowered, so any ``create_app`` boot seeds a
    principal cheaply. The FastAPI ``TestClient`` is patched to auto-attach the
    seeded API key on ``__enter__`` (after lifespan seeding), so the existing
    API suite authenticates through the default-deny perimeter with no per-test
    change; negative-path tests drop the header explicitly."""
    from cryptography.fernet import Fernet, MultiFernet

    from foragerr import keystore as keystore_mod
    from foragerr.auth import bootstrap as bootstrap_mod
    from foragerr.auth import passwords as passwords_mod

    for key in list(os.environ):
        if key.startswith("FORAGERR_"):
            monkeypatch.delenv(key)
    flog.clear_secrets()

    monkeypatch.setattr(keystore_mod, "SCRYPT_N", 2**4)
    monkeypatch.setattr(keystore_mod, "_new_salt", lambda: b"0123456789abcdef")
    monkeypatch.setattr(passwords_mod, "SCRYPT_N", 2**4)
    # Pin the seeded API key so the auto-auth client authenticates across reboots
    # over the same principal (a later boot mints no new key).
    monkeypatch.setattr(bootstrap_mod, "_new_api_key", lambda: TEST_API_KEY)
    monkeypatch.setenv("FORAGERR_SECRET_KEY", TEST_SECRET_KEY)
    monkeypatch.setenv("FORAGERR_ADMIN_USER", TEST_ADMIN_USER)
    monkeypatch.setenv("FORAGERR_ADMIN_PASSWORD", TEST_ADMIN_PASSWORD)
    fernet_key = keystore_mod.derive_fernet_key(TEST_SECRET_KEY, keystore_mod._new_salt())
    keystore_mod.install_keystore(
        keystore_mod.Keystore(MultiFernet([Fernet(fernet_key)]), available=True)
    )

    _install_auto_auth_testclient(monkeypatch)

    yield

    keystore_mod.reset_keystore()
    flog.clear_secrets()
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_foragerr", False):
            root.removeHandler(handler)
            handler.close()


def _install_auto_auth_testclient(monkeypatch) -> None:
    """Patch ``TestClient.__enter__`` to attach the seeded API key by default.

    After the real ``__enter__`` runs the lifespan (which seeds the principal
    and stashes the raw key on ``app.state.bootstrap_api_key``), attach it as
    ``X-Api-Key`` so every subsequent request/websocket authenticates through
    the perimeter. Only applied when the app actually seeded a key and the test
    has not already set its own ``X-Api-Key``. Negative-path tests call
    ``client.headers.pop("X-Api-Key", None)`` to send bare requests."""
    import starlette.testclient as stc

    original_enter = stc.TestClient.__enter__

    def auto_auth_enter(self):
        result = original_enter(self)
        app = getattr(self, "app", None)
        # Attach the pinned key on any real foragerr app (one that seeded a
        # principal at lifespan startup). A bare FastAPI() test app has no db and
        # no perimeter, so the header is harmless there. Tests exercising the
        # unauthenticated perimeter drop it: client.headers.pop("X-Api-Key").
        has_db = getattr(getattr(app, "state", None), "db", None) is not None
        if has_db and not any(k.lower() == "x-api-key" for k in self.headers):
            self.headers["X-Api-Key"] = TEST_API_KEY
        return result

    monkeypatch.setattr(stc.TestClient, "__enter__", auto_auth_enter)


@pytest.fixture
def config_dir(tmp_path: Path, monkeypatch) -> Path:
    """A fresh config directory, exported as FORAGERR_CONFIG_DIR."""
    path = tmp_path / "cfg"
    path.mkdir()
    monkeypatch.setenv("FORAGERR_CONFIG_DIR", str(path))
    return path


# --- db / sched area fixtures -------------------------------------------------


async def eventually(predicate, *, timeout: float = 5.0, interval: float = 0.02):
    """Poll ``predicate`` (sync or async) until truthy; fail after timeout."""
    deadline = time.monotonic() + timeout
    while True:
        result = predicate()
        if asyncio.iscoroutine(result):
            result = await result
        if result:
            return result
        if time.monotonic() > deadline:
            raise AssertionError(f"condition not met within {timeout}s: {predicate}")
        await asyncio.sleep(interval)


@pytest.fixture
def migrated_dir(tmp_path: Path) -> Path:
    """A config dir whose database has been migrated to head."""
    from foragerr.db import prepare_database

    path = tmp_path / "dbcfg"
    path.mkdir()
    prepare_database(path)
    return path


@pytest.fixture
async def db(migrated_dir: Path):
    """A live Database over a head-revision schema."""
    from foragerr.db import Database

    database = Database(db_path=migrated_dir / "foragerr.db")
    yield database
    await database.close()


@pytest.fixture
def command_registry():
    """Snapshot/restore the command + handler registries around a test."""
    from foragerr.commands.registry import restore_registry, snapshot_registry

    snapshot = snapshot_registry()
    yield
    restore_registry(snapshot)


def define_command(
    name: str,
    *,
    workload_class: str = "default",
    exclusivity_group: str | None = None,
    default_priority: int = 0,
):
    """Register a throwaway command type with a single ``token`` payload field."""
    from foragerr.commands.registry import BaseCommand, register_command

    cls = type(
        f"TestCmd_{name}",
        (BaseCommand,),
        {
            "__annotations__": {"name": Literal[name], "token": Optional[str]},
            "name": name,
            "token": None,
            "workload_class": workload_class,
            "exclusivity_group": exclusivity_group,
            "default_priority": default_priority,
            "__module__": __name__,
        },
    )
    return register_command(cls)


async def seed_series_issue(db, tmp_path) -> tuple[int, int]:
    """One monitored series ("Spawn") with one monitored issue (#1) under a
    fresh root folder; returns ``(series_id, issue_id)``.

    Shared by the daily-surfaces API test files (history / blocklist / …) that
    each used to carry an identical private copy of this seed."""
    import datetime as dt

    from sqlalchemy import select

    from foragerr.library import repo
    from foragerr.quality.models import DEFAULT_PROFILE_NAME, FormatProfileRow

    root = tmp_path / "lib-root"
    root.mkdir(exist_ok=True)
    async with db.read_session() as session:
        profile_id = (
            await session.execute(
                select(FormatProfileRow.id).where(
                    FormatProfileRow.name == DEFAULT_PROFILE_NAME
                )
            )
        ).scalar_one()
    async with db.write_session() as session:
        rf = await repo.create_root_folder(session, str(root))
        series = await repo.create_series(
            session,
            cv_volume_id=987654,
            title="Spawn",
            start_year=2024,
            format_profile_id=profile_id,
            root_folder_id=rf.id,
            path=str(root / "Spawn"),
            monitored=True,
        )
        await session.flush()
        issue = await repo.create_issue(
            session,
            series_id=series.id,
            cv_issue_id=123456,
            issue_number="1",
            cover_date=dt.date(2024, 1, 1),
            monitored=True,
        )
        await session.flush()
        return series.id, issue.id


@pytest.fixture
async def service(db, command_registry):
    """A running CommandService with default pool sizes and a fast poll."""
    from foragerr.commands import CommandService

    svc = CommandService(db, poll_interval=0.05)
    await svc.start()
    yield svc
    await svc.drain(1.0)
