"""Shared fixtures: env/log isolation for the foundation test suite."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
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
    _install_deterministic_ws_teardown(monkeypatch)

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


#: How long a WebSocket test session waits for the ASGI app to finish after the
#: client disconnect before falling back to starlette's own (racy) teardown.
#: Only a deadlock guard — the real wait is microseconds.
WS_APP_TEARDOWN_TIMEOUT = 10.0


def _install_deterministic_ws_teardown(monkeypatch) -> None:
    """Make ``WebSocketTestSession`` teardown wait for the ASGI app to finish.

    starlette's ``WebSocketTestSession.__exit__`` sends ``websocket.disconnect``
    and then *immediately* cancels the anyio scope running the ASGI app::

        fut, cs = portal.start_task(self._run)
        stack.callback(fut.result)              # 3rd on the way out
        stack.callback(portal.call, cs.cancel)  # 2nd on the way out
        ...
        stack.callback(self.close, 1000)        # 1st on the way out

    Nothing makes the event loop finish the endpoint between ``close`` and
    ``cs.cancel``. ``/api/v1/ws`` teardown is several event-loop turns long
    (``asyncio.wait`` returns, the broadcaster deregisters, the pump task is
    cancelled and awaited), so when the box is oversubscribed — 14 xdist
    workers on 14 cores — the cancel can land *inside* that cleanup. The
    endpoint's ``CancelledError`` then escapes ``_run``, anyio's portal marks
    the future CANCELLED, and ``fut.result()`` raises
    ``concurrent.futures.CancelledError`` out of the ``with ws:`` block. That
    is the whole flake: a harness race, not a product defect, which is why it
    only ever hit tests that *accept* a socket and why every rerun passed.

    The fix removes the race instead of tolerating it: wrap the ASGI app so it
    signals a ``threading.Event`` when its coroutine returns, and block in
    ``close()`` (and on the handshake-denial path) until that fires. By the
    time starlette cancels, there is nothing left to cancel."""
    import starlette.testclient as stc

    original_enter = stc.WebSocketTestSession.__enter__
    original_close = stc.WebSocketTestSession.close
    original_raise_on_close = stc.WebSocketTestSession._raise_on_close

    def enter(self):
        done = threading.Event()
        self._foragerr_app_done = done
        inner = self.app

        async def app_signalling_completion(scope, receive, send):
            try:
                return await inner(scope, receive, send)
            finally:
                done.set()

        self.app = app_signalling_completion
        return original_enter(self)

    def wait_for_app(self) -> None:
        done = getattr(self, "_foragerr_app_done", None)
        if done is not None:
            done.wait(WS_APP_TEARDOWN_TIMEOUT)

    def close(self, code: int = 1000, reason=None):
        result = original_close(self, code, reason)
        wait_for_app(self)
        return result

    def raise_on_close(self, message):
        try:
            return original_raise_on_close(self, message)
        except BaseException:
            # A refused handshake (1008 / denial response) unwinds ``__enter__``
            # straight into the same cancel-then-``fut.result()`` sequence, so
            # let the endpoint finish unwinding before the scope is cancelled.
            wait_for_app(self)
            raise

    monkeypatch.setattr(stc.WebSocketTestSession, "__enter__", enter)
    monkeypatch.setattr(stc.WebSocketTestSession, "close", close)
    monkeypatch.setattr(stc.WebSocketTestSession, "_raise_on_close", raise_on_close)


@pytest.fixture(autouse=True)
def _reset_loop_bound_globals():
    """Drop every process-global asyncio primitive between tests.

    The rate gates, politeness locks and render/fetch semaphores are module-level
    by design (spacing and concurrency caps must hold however many clients
    exist), but an ``asyncio.Lock``/``Semaphore`` binds to the first event loop
    that *contends* on it and then refuses any other with ``RuntimeError: ... is
    bound to a different event loop``. Every async test gets a fresh loop, so a
    gate surviving from a previous test is a live landmine that only goes off
    under contention — i.e. intermittently, on a rotating cast of tests. Several
    test modules already carry their own ``reset_gate(s)`` fixture; doing it once
    here makes the guarantee unconditional instead of opt-in."""
    from foragerr.api import config_resources, cover_proxy
    from foragerr.ddl import politeness
    from foragerr.indexers import ratelimit as indexer_ratelimit
    from foragerr.metadata import ratelimit as cv_ratelimit
    from foragerr.opds import router as opds_router
    from foragerr.sources import ratelimit as source_ratelimit

    def reset() -> None:
        cv_ratelimit.reset_gate()
        source_ratelimit.reset_gates()
        indexer_ratelimit.reset_gates()
        politeness.reset_locks()
        cover_proxy._fetch_semaphore = None  # rebuilt lazily on the next request
        opds_router._render_semaphore = asyncio.Semaphore(
            opds_router._RENDER_CONCURRENCY
        )
        config_resources._config_write_lock = asyncio.Lock()

    reset()
    yield
    reset()


@asynccontextmanager
async def running_app(settings):
    """A fully started app + ASGI-transport client, all on ONE event loop.

    Yields ``(app, client)``: the lifespan is driven on the CURRENT loop and the
    client is an ``httpx.AsyncClient`` over ``ASGITransport``, so HTTP calls,
    the DB, the command workers, the scheduler and the test body all share one
    loop. ``client.app`` is set so a fixture can yield the client alone and its
    tests still reach ``app.state``.

    Why this exists — ``TestClient`` runs the lifespan (and therefore the
    ``Database``, the command pool and the scheduler) on a private portal
    thread with its OWN event loop. An ``async def`` test that then awaits
    ``app.state.db`` directly drives that one ``Database`` — and its
    ``asyncio.Lock`` write gate — from pytest-asyncio's loop as well. Two loops,
    one lock. ``asyncio.Lock.acquire`` only consults its bound loop on the
    CONTENDED path, so this is invisible until a background worker happens to
    hold the write lock at the moment the test writes; then it is
    ``RuntimeError: <asyncio.locks.Lock ...> is bound to a different event
    loop``, on a rotating cast of tests, and it gets likelier the busier the
    box (which is why parallel runs surfaced it). Driving the lifespan on the
    current loop deletes the second loop instead of tolerating it.

    Sync tests can keep using ``TestClient``; they already reach the app's loop
    for direct DB work through ``client.portal.call`` (see test_opds_head.py,
    test_series_groups_api.py). Async tests that touch ``app.state`` use this.
    """
    import httpx

    from foragerr.app import create_app

    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Auth: the default-deny perimeter (FRG-AUTH-010) applies here too,
            # and this client is not the patched TestClient, so attach the key
            # the lifespan just seeded. Tests exercising the bare perimeter pop
            # it, exactly as they do on TestClient.
            client.headers["X-Api-Key"] = app.state.bootstrap_api_key
            client.app = app
            yield app, client


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
