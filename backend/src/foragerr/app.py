"""FastAPI application factory and uvicorn entrypoint (FRG-API-001).

Design (m1-foundation, decisions 1 and 10): ``create_app()`` builds a fully
independent application per call — no import-time singletons. Configuration
is loaded (env > config.yaml > defaults), logging is configured, and routers
are mounted under ``/api/v1`` (OpenAPI at ``/api/v1/openapi.json``).

Extension points for the other m1-foundation work areas
-------------------------------------------------------
Lifespan wiring uses two ordered hook lists created per app:

- ``app.state.startup_hooks``  — ``async (app) -> None``, run in registration
  order when the app starts (db engine/migrations first, then scheduler).
- ``app.state.shutdown_hooks`` — ``async (app) -> None``, run in REVERSE
  registration order on shutdown (scheduler drain before DB close/WAL
  checkpoint), inside uvicorn's lifespan so SIGTERM flows through here.

Area modules register by appending inside ``create_app()`` at the marked
blocks (db, sched) or by mounting routers on ``api_router`` (api area).
``app.state.settings`` carries the effective :class:`Settings`.
"""

from __future__ import annotations

import logging
import signal
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI

from foragerr.api import register_api
from foragerr.commands import register_scheduler
from foragerr.config import ConfigError, Settings, load_settings
from foragerr.db import register_database
from foragerr.logging import setup_logging

logger = logging.getLogger("foragerr.app")


def _load_settings_or_exit() -> Settings:
    """Fail-fast path (FRG-NFR-009): invalid config -> stderr + non-zero exit."""
    try:
        return load_settings()
    except ConfigError as exc:
        # sys.stderr.write, not a print call: backend/src is print-free by
        # convention (FRG-NFR-008 static guard — stdout writes that bypass
        # the redaction filter are banned).
        sys.stderr.write(f"foragerr: fatal configuration error\n{exc}\n")
        raise SystemExit(2) from exc


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    for hook in app.state.startup_hooks:
        await hook(app)
    logger.info("foragerr application started")
    yield
    logger.info("foragerr application shutting down")
    for hook in reversed(app.state.shutdown_hooks):
        await hook(app)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build an independent foragerr application.

    ``settings=None`` (the uvicorn ``--factory`` path) loads configuration
    from ``FORAGERR_CONFIG_DIR``/env/config.yaml; tests may inject a
    pre-built :class:`Settings`.
    """
    if settings is None:
        settings = _load_settings_or_exit()
    setup_logging(
        settings.config_dir,
        level=settings.log_level,
        max_bytes=settings.log_max_bytes,
        backup_count=settings.log_backup_count,
    )

    app = FastAPI(
        title="foragerr",
        lifespan=_lifespan,
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs",
        redoc_url=None,
        # FastAPI's oauth2-redirect helper route defaults to "/docs/..." even
        # with a custom docs_url, and would be the one route outside
        # /api/v1 (FRG-API-001). No auth/OAuth2 exists in M1 (FRG-AUTH-001)
        # so the redirect helper is unused; disable it outright.
        swagger_ui_oauth2_redirect_url=None,
    )
    app.state.settings = settings
    app.state.startup_hooks = []  # async (app) -> None, run in order at startup
    app.state.shutdown_hooks = []  # async (app) -> None, run reversed at shutdown

    # --- db area (tasks 2.x): engine/migration startup + WAL-checkpoint
    #     shutdown (registered BEFORE sched so shutdown runs after drain) ---
    register_database(app)

    # --- sched area (tasks 3.x): worker pools + scheduler startup, graceful
    #     drain shutdown (FRG-SCHED-011) ---
    register_scheduler(app)

    # --- api area (tasks 5.x): error handling, health, version, command
    #     routers (FRG-API-001/002, FRG-DEP-007/010, FRG-AUTH-001) ---
    register_api(app)

    return app


def main() -> None:
    """Console entrypoint: run uvicorn on the configured host/port (8789).

    FRG-DEP-008 requires a clean exit code 0 on SIGTERM/SIGINT. Uvicorn's own
    signal handling runs our graceful shutdown correctly (lifespan hooks
    drain the queue and WAL-checkpoint) but then deliberately re-raises the
    captured signal against the *restored* pre-existing disposition once
    shutdown completes, so a caller can observe "died from signal N" — by
    default that pre-existing disposition is the interpreter's default
    action, which terminates the process (a negative/128+N exit status, not
    0). Pre-installing SIG_IGN makes that post-shutdown re-raise a no-op:
    during the run, uvicorn still overrides the disposition with its own
    handler (which is what actually triggers the graceful shutdown), so
    behavior while serving is unaffected.
    """
    settings = _load_settings_or_exit()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, signal.SIG_IGN)
    uvicorn.run(
        "foragerr.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_config=None,  # keep foragerr's structured logging configuration
    )


if __name__ == "__main__":
    main()
