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
import threading
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI
from types import FrameType

from foragerr.api import register_api
from foragerr.commands import register_scheduler
from foragerr.commands.service import OFFLOAD_THREAD_PREFIX
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
    completed = 0
    try:
        for hook in app.state.startup_hooks:
            await hook(app)
            completed += 1
    except Exception:
        # A later startup hook failed. The earlier ones already acquired
        # resources (DB engine open, WAL unchecked) — run the shutdown hooks
        # best-effort so nothing is left dangling before the failure surfaces.
        logger.exception(
            "foragerr startup failed after %d hook(s); running shutdown cleanup",
            completed,
        )
        for hook in reversed(app.state.shutdown_hooks):
            try:
                await hook(app)
            except Exception:  # never mask the original startup failure
                logger.exception("foragerr: shutdown hook failed during cleanup")
        raise
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
    app.state.process_started_at = time.monotonic()  # FRG-API-014 uptime_seconds
    app.state.startup_hooks = []  # async (app) -> None, run in order at startup
    app.state.shutdown_hooks = []  # async (app) -> None, run reversed at shutdown

    # --- ops/health-backups area (m2-ops-health-backups): importing the module
    #     registers the backup-database command + handler (mirrors the
    #     ddl.commands / downloads.tracking bare-import pattern). The
    #     restore-marker startup hook (FRG-DB-010) MUST run FIRST — before
    #     register_database opens the engine below — so it is appended here,
    #     ahead of the db area. ---
    from foragerr.db.backup_command import (
        quick_check_startup_hook,
        register_backup_task,
        restore_marker_startup_hook,
    )

    app.state.startup_hooks.append(restore_marker_startup_hook)

    # --- db area (tasks 2.x): engine/migration startup + WAL-checkpoint
    #     shutdown (registered BEFORE sched so shutdown runs after drain) ---
    register_database(app)

    # Startup integrity quick_check (FRG-DB-012) runs AFTER the db area above
    # has prepared/opened the database, so it checks the live file.
    app.state.startup_hooks.append(quick_check_startup_hook)

    # --- sched area (tasks 3.x): worker pools + scheduler startup, graceful
    #     drain shutdown (FRG-SCHED-011) ---
    register_scheduler(app)

    async def _register_backup_database_task(app: FastAPI) -> None:
        await register_backup_task(app.state.scheduler, app.state.settings)

    # Registers the "backup-database" scheduled task (FRG-DB-009); runs after
    # the scheduler above has created app.state.scheduler.
    app.state.startup_hooks.append(_register_backup_database_task)

    # --- library flows (change 3): importing registers the chained
    #     refresh-series/scan-series/series-search commands + handlers
    #     (FRG-SER-005/006/007, FRG-META-008). A bare import for the decorator
    #     side effect is sufficient — the flows keep no app-level state. ---
    from foragerr.library import flows as _library_flows  # noqa: F401

    # --- api area (tasks 5.x): error handling, health, version, command
    #     routers (FRG-API-001/002, FRG-DEP-007/010, FRG-AUTH-001) ---
    register_api(app)

    # --- indexers area (m1-search-indexers): provider schema + test endpoints
    #     under /api/v1/indexer (FRG-IDX-003, FRG-API-009) ---
    from foragerr.api.indexers import router as indexer_router

    app.include_router(indexer_router, prefix="/api/v1")

    # --- downloads area (m1-downloads, area: downloads): download-client
    #     provider schema + test endpoints under /api/v1/downloadclient
    #     (FRG-DL-002, FRG-API-009). Importing the package maps the six change-5
    #     ORM models onto Base.metadata. ---
    import foragerr.downloads  # noqa: F401 — ORM model registration
    from foragerr.api.downloadclient import router as downloadclient_router

    app.include_router(downloadclient_router, prefix="/api/v1")

    # --- library config lists (m1-ui-opds-deploy): read-only root-folder and
    #     format-profile pickers for the add-series flow (FRG-SER-008,
    #     FRG-QUAL-001, FRG-UI-005) under /api/v1 ---
    from foragerr.api.library_config import router as library_config_router

    app.include_router(library_config_router, prefix="/api/v1")

    # --- config resources + rename (m2-settings-naming-config): typed
    #     naming/media-management config singletons (FRG-API-013) and the
    #     rename preview/execute endpoints (FRG-PP-012) under /api/v1. Importing
    #     the library flows above registered the rename-series command. ---
    from foragerr.api.config_resources import router as config_resources_router
    from foragerr.api.rename import router as rename_router

    app.include_router(config_resources_router, prefix="/api/v1")
    app.include_router(rename_router, prefix="/api/v1")

    # --- manual import (m2-manual-import): importing the module registers the
    #     manual-import pp-pool command + handler (FRG-PP-016); mount the
    #     list/execute endpoints (FRG-API-015) under /api/v1. ---
    import foragerr.downloads.manual_import  # noqa: F401 — command/handler registration
    from foragerr.api.manual_import import router as manual_import_router

    app.include_router(manual_import_router, prefix="/api/v1")

    # --- issue-file deletion (m2-daily-surfaces): user file deletion routed
    #     through the recycle bin via the delete_issue_file flow
    #     (FRG-API-003, FRG-UI-004, FRG-PP-013) under /api/v1. ---
    from foragerr.api.issuefile import router as issuefile_router

    app.include_router(issuefile_router, prefix="/api/v1")

    # --- library import (m2-existing-library-import): the scan/execute
    #     commands + handlers registered via the ``foragerr.library.flows``
    #     import above (FRG-IMP-022/023); mount the staging review endpoints. ---
    from foragerr.api.library_import import router as library_import_router

    app.include_router(library_import_router, prefix="/api/v1")

    # --- search integration (m1-search-indexers, area 3): importing registers
    #     the search / grab / prune commands + handlers (FRG-SRCH-008/009/014,
    #     FRG-API-008); mount the interactive-search release router; register
    #     the scheduled backlog + cache-prune tasks. A shared caps cache lives
    #     on app.state for the interactive-search request path (FRG-IDX-004). ---
    import foragerr.search_ops  # noqa: F401 — command/handler registration
    from foragerr.api.release import router as release_router
    from foragerr.indexers.caps import CapsCache

    app.include_router(release_router, prefix="/api/v1")
    app.state.caps_cache = CapsCache()

    async def _register_search_tasks(app: FastAPI) -> None:
        scheduler = app.state.scheduler
        settings = app.state.settings
        await scheduler.register_task(
            "backlog-search",
            "backlog-search",
            interval_seconds=settings.backlog_search_interval_seconds,
            min_interval_seconds=3600,
        )
        await scheduler.register_task(
            "prune-release-cache",
            "prune-release-cache",
            interval_seconds=1800,
            min_interval_seconds=300,
        )

    # Runs after the scheduler startup hook (which creates app.state.scheduler),
    # since it is appended after register_scheduler(app) above.
    app.state.startup_hooks.append(_register_search_tasks)

    # --- downloads tracking area (m1-downloads, area: tracking): importing the
    #     module registers TrackDownloadsCommand + handler (FRG-DL-007); mount
    #     the queue read/remove router (FRG-DL-008, FRG-API-007); register the
    #     ~1-minute tracking task. ---
    import foragerr.downloads.tracking  # noqa: F401 — command/handler registration
    from foragerr.api.queue import router as queue_router

    app.include_router(queue_router, prefix="/api/v1")

    async def _register_tracking_task(app: FastAPI) -> None:
        await app.state.scheduler.register_task(
            "track-downloads",
            "track-downloads",
            interval_seconds=app.state.settings.track_downloads_interval_seconds,
            min_interval_seconds=60,
        )

    app.state.startup_hooks.append(_register_tracking_task)

    # --- daily surfaces (m2-daily-surfaces): the history feed over
    #     import_history (FRG-API-011), the derived wanted/missing list
    #     (FRG-API-012), and the blocklist read/remove surface (FRG-UI-017)
    #     under /api/v1. Read-only over existing tables (plus the blocklist
    #     row deletes); no new commands or tasks. ---
    from foragerr.api.blocklist import router as blocklist_router
    from foragerr.api.history import router as history_router
    from foragerr.api.wanted import router as wanted_router

    app.include_router(history_router, prefix="/api/v1")
    app.include_router(wanted_router, prefix="/api/v1")
    app.include_router(blocklist_router, prefix="/api/v1")

    # --- pull area (m3-pull-backbone, area E): the read-only weekly pull
    #     resource, GET /api/v1/pull (FRG-API-019) — the metadata-derived
    #     projection (FRG-PULL-001) merged with any stored pull entries
    #     (FRG-PULL-003). No commands/tasks registered here: the fetch client,
    #     matcher, and refresh command (areas B/C/D of this same change) land
    #     in later commits and this router works standalone against whatever
    #     is already in the library + `pull_entries` (empty table included). ---
    from foragerr.api.pull import router as pull_router

    app.include_router(pull_router, prefix="/api/v1")

    # --- pull refresh (m3-pull-backbone, area D): importing the module registers
    #     the pull-refresh command + handler (fetch → store → match →
    #     refresh-series trigger, FRG-PULL-005/006). Register the scheduled
    #     weekly-pull task, interval from config (default 4 h, min-clamped to
    #     1 h). Runs after register_scheduler above (which creates
    #     app.state.scheduler). Manual force-refresh is the generic FRG-SCHED-007
    #     surface (POST /api/v1/system/task/pull-refresh), which bypasses the
    #     scheduler's interval gate (the re-poll throttle). ---
    import foragerr.pull.commands  # noqa: F401 — command/handler registration
    from foragerr.pull.commands import register_pull_refresh_task

    async def _register_pull_refresh_task(app: FastAPI) -> None:
        await register_pull_refresh_task(app.state.scheduler, app.state.settings)

    app.state.startup_hooks.append(_register_pull_refresh_task)

    # --- import flows (m1-import-pipeline, area: flows): importing the module
    #     registers ProcessImportsCommand + handler (FRG-DL-009/010); register
    #     the ~1-minute pp-pool drain that runs the completed downloads through
    #     the shared import pipeline. ---
    import foragerr.downloads.imports  # noqa: F401 — command/handler registration
    from foragerr.downloads.imports import (
        PROCESS_IMPORTS_INTERVAL,
        PROCESS_IMPORTS_MIN_INTERVAL,
        PROCESS_IMPORTS_TASK,
    )

    async def _register_process_imports_task(app: FastAPI) -> None:
        await app.state.scheduler.register_task(
            PROCESS_IMPORTS_TASK,
            PROCESS_IMPORTS_TASK,
            interval_seconds=PROCESS_IMPORTS_INTERVAL,
            min_interval_seconds=PROCESS_IMPORTS_MIN_INTERVAL,
        )

    app.state.startup_hooks.append(_register_process_imports_task)

    # --- ddl area (m1-downloads, area: ddl): importing registers the DDL
    #     client factory, the GetComics search provider, and the
    #     process-ddl-queue command; the task drains the persistent queue. ---
    import foragerr.ddl  # noqa: F401 — client/provider/command registration
    from foragerr.ddl.commands import (
        PROCESS_DDL_QUEUE_INTERVAL,
        PROCESS_DDL_QUEUE_MIN_INTERVAL,
        PROCESS_DDL_QUEUE_TASK,
    )

    async def _register_ddl_tasks(app: FastAPI) -> None:
        await app.state.scheduler.register_task(
            PROCESS_DDL_QUEUE_TASK,
            PROCESS_DDL_QUEUE_TASK,
            interval_seconds=PROCESS_DDL_QUEUE_INTERVAL,
            min_interval_seconds=PROCESS_DDL_QUEUE_MIN_INTERVAL,
        )

    app.state.startup_hooks.append(_register_ddl_tasks)

    # --- first-run seeding (m2-first-run-defaults, area B): seed the default
    #     keyless GetComics indexer + built-in DDL client once per database,
    #     gated on a persisted marker (FRG-DEP-013). Appended as a startup hook
    #     so it runs AFTER the db area's migration/engine startup hook (which
    #     ran migrations and set app.state.db) and after the ``import
    #     foragerr.ddl`` above has populated the getcomics/ddl registry. ---
    from foragerr.db.first_run import first_run_seed_startup_hook

    app.state.startup_hooks.append(first_run_seed_startup_hook)

    # --- ws area (m1-ui-opds-deploy, area: ws): mount /api/v1/ws and, at
    #     startup, subscribe the broadcaster to app.state.events (created by
    #     register_scheduler above, so this MUST follow it) (FRG-API-010). ---
    from foragerr.ws import register_ws

    register_ws(app)

    # --- opds area (m1-ui-opds-deploy, area: opds): mount the OPDS 1.2
    #     catalog at the configured base path (default /opds). Unauthenticated
    #     read surface; id-only file resolution (FRG-OPDS-001..006). ---
    from foragerr.opds import register_opds

    register_opds(app)

    # --- spa area (m1-ui-opds-deploy, area: deploy): serve the built React SPA
    #     statically at "/" (FRG-DEP-001). Mounted LAST so the API / OPDS / health
    #     routers above always win; only unclaimed paths reach the SPA. No-op when
    #     the dist bundle is absent (running from source / tests) so create_app
    #     stays importable without a frontend build. ---
    from foragerr.spa import register_spa

    register_spa(app)

    return app


class _ForagerrServer(uvicorn.Server):
    """Uvicorn server that lets a REPEATED shutdown signal force-exit.

    Uvicorn's own ``handle_exit`` only escalates to ``force_exit`` on a second
    SIGINT; a second SIGTERM — the docker/systemd restart-then-kill pattern —
    does nothing once ``should_exit`` is set, so an operator who signals twice
    cannot cut short a wedged shutdown. Escalate on ANY repeat signal so the
    ≤30s bound (FRG-DEP-008) can always be forced."""

    def handle_exit(self, sig: int, frame: FrameType | None) -> None:
        if self.should_exit:
            self.force_exit = True
        super().handle_exit(sig, frame)


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
    app = create_app(settings)
    config = uvicorn.Config(
        app,
        host=settings.host,
        port=settings.port,
        log_config=None,  # keep foragerr's structured logging configuration
    )
    _ForagerrServer(config).run()

    # Shutdown (drain + WAL checkpoint) completed inside run(). A blocking
    # handler that outlived the drain grace is now an abandoned DAEMON thread
    # (see commands.service.daemon_offload); it dies with the process and its
    # command row is recovered on the next start (FRG-SCHED-002). Name it at
    # CRITICAL so the operator can see WHAT was abandoned past the bound.
    stuck = [
        t.name[len(OFFLOAD_THREAD_PREFIX):]
        for t in threading.enumerate()
        if t.name.startswith(OFFLOAD_THREAD_PREFIX) and t.is_alive()
    ]
    if stuck:
        logger.critical(
            "shutdown: %d command handler(s) still running past the drain "
            "grace were abandoned to daemon threads (orphan recovery re-runs "
            "them next start): %s",
            len(stuck),
            ", ".join(sorted(stuck)),
        )


if __name__ == "__main__":
    main()
