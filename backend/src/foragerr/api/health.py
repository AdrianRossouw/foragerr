"""Root-level, unauthenticated health endpoint (FRG-DEP-007, FRG-AUTH-010).

``GET /health`` — deliberately NOT under ``/api/v1`` (FRG-API-001 scenario
explicitly excludes it) and carries zero credentials: it is on the default-deny
perimeter's fixed exempt list (``foragerr.auth.perimeter.EXEMPT_PATHS``) so a
Docker/monitoring probe reaches it without credentials. Reports liveness plus
per-component readiness: database (``db.health()``), workers
(``commands.health()``), scheduler (derived from ``scheduler.status()``
succeeding), and migration state (current Alembic revision at head). 200
when every component is healthy; 503 naming the failing component(s)
otherwise — suitable for a Docker ``HEALTHCHECK``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter, FastAPI, Request, Response

from foragerr.db.migrations import ALEMBIC_DIR, current_revision

router = APIRouter()


def _head_revision(script_location: Path = ALEMBIC_DIR) -> str | None:
    """The migration head known to this build (no DB access)."""
    cfg = Config()
    cfg.set_main_option("script_location", str(script_location))
    return ScriptDirectory.from_config(cfg).get_current_head()


async def cache_migration_head(app: FastAPI) -> None:
    """Resolve the migration head ONCE at startup (a startup hook).

    The head is immutable while the process runs (no self-update, FRG-DEP-009),
    so parsing the Alembic script tree per ``/health`` probe would burn event-
    loop time for a value that never changes. Cache it on ``app.state`` and let
    each probe only read the DB's current revision off the loop (FRG-DEP-007)."""
    try:
        app.state.migration_head = await asyncio.to_thread(_head_revision)
    except Exception:  # pragma: no cover - the bundled script tree always parses
        app.state.migration_head = None


async def _migration_health(head: str | None, db_path: Path) -> dict[str, Any]:
    try:
        # Read the DB's stamped revision off the event loop; no Alembic parse
        # happens here — the head is the value cached at startup.
        current = await asyncio.to_thread(current_revision, db_path)
        if current == head:
            return {"status": "up", "revision": current}
        return {"status": "down", "current": current, "head": head}
    except Exception as exc:  # pragma: no cover - defensive
        return {"status": "down", "error": str(exc)}


async def _scheduler_health(scheduler: Any) -> dict[str, Any]:
    """Derived from ``status()`` succeeding: a stopped/crashed loop task
    surfaces as a failing status probe (the backbone exposes no separate
    running flag)."""
    try:
        tasks = await scheduler.status()
    except Exception as exc:
        return {"status": "down", "error": str(exc)}
    return {"status": "up", "tasks": tasks}


async def probe_components(app: Any) -> dict[str, dict[str, Any]]:
    """The container-probe component detail (database, workers, scheduler,
    migrations). Shared by the slim root probe (which reduces it to names)
    and the authenticated system surface (which returns it whole)."""
    db = app.state.db
    return {
        "database": await db.health(),
        "workers": app.state.commands.health(),
        "scheduler": await _scheduler_health(app.state.scheduler),
        "migrations": await _migration_health(
            getattr(app.state, "migration_head", None), db.db_path
        ),
    }


@router.get("/health", include_in_schema=False)
async def health(request: Request, response: Response) -> dict[str, Any]:
    # FRG-SEC-008 / FRG-DEP-007: this endpoint is unauthenticated (Docker
    # HEALTHCHECK), so the body is MINIMAL — overall status, plus the failing
    # component NAMES when unhealthy. Paths, revisions, task lists, and error
    # text stay behind auth on /api/v1/system/health/components.
    components = await probe_components(request.app)
    failing = [name for name, comp in components.items() if comp.get("status") != "up"]
    if failing:
        response.status_code = 503
        return {"status": "down", "failing": failing}
    return {"status": "up"}
