"""foragerr API area: uniform error handling, paging, health, version, and
command/series/issues transport (FRG-API-001..006, FRG-DEP-007, FRG-DEP-010,
FRG-AUTH-001).

:func:`register_api` is the app factory's extension point (mirrors
``register_database``/``register_scheduler``): it installs the uniform-shape
exception handlers, mounts ``/api/v1/system/status``, ``/api/v1/command*``,
``/api/v1/series*`` and ``/api/v1/issues*``, mounts root-level ``/health``,
and logs the version line at startup.

No auth (FRG-AUTH-001, M1 accepted risk): this module registers no
middleware and no auth dependency on the app or on any router — every route
mounted here (including the series/issues routers) responds credential-free
by construction.
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI

from foragerr.api.command import router as command_router
from foragerr.api.errors import ApiError, register_error_handlers
from foragerr.api.health import cache_migration_head
from foragerr.api.limits import install_request_limits
from foragerr.api.health import router as health_router
from foragerr.api.issues import router as issues_router
from foragerr.api.series import router as series_router
from foragerr.api.system import log_startup_version
from foragerr.api.system import router as system_router

__all__ = ["ApiError", "register_api"]


def register_api(app: FastAPI) -> None:
    register_error_handlers(app)

    # Listener inbound resource limits (FRG-NFR-014): a single ASGI middleware
    # on the HTTP scope — body/header/timeout/per-client-rate caps — installed
    # here so it wraps every mounted route (API, OPDS, health, SPA) while never
    # touching the long-lived WebSocket (websocket scope passes through).
    install_request_limits(app)

    api_router = APIRouter()
    api_router.include_router(system_router)
    api_router.include_router(command_router)
    api_router.include_router(series_router)
    api_router.include_router(issues_router)
    app.include_router(api_router, prefix="/api/v1")

    app.include_router(health_router)  # root level, NOT under /api/v1

    async def _log_version(_app: FastAPI) -> None:
        log_startup_version()

    # The version line is a spec contract (FRG-DEP-010): emit it FIRST, before
    # any other startup hook runs — it reads only env/package metadata and has
    # no dependency on the db/scheduler that register earlier.
    app.state.startup_hooks.insert(0, _log_version)

    # Resolve the immutable migration head once at startup so /health never
    # parses Alembic on the event loop per probe (FRG-DEP-007).
    app.state.startup_hooks.append(cache_migration_head)
