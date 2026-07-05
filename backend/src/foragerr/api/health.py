"""Root-level, unauthenticated health endpoint (FRG-DEP-007, FRG-AUTH-001).

``GET /health`` — deliberately NOT under ``/api/v1`` (FRG-API-001 scenario
explicitly excludes it) and carries zero credentials. Reports liveness plus
per-component readiness: database (``db.health()``), workers
(``commands.health()``), scheduler (derived from ``scheduler.status()``
succeeding), and migration state (current Alembic revision at head). 200
when every component is healthy; 503 naming the failing component(s)
otherwise — suitable for a Docker ``HEALTHCHECK``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Request, Response

from foragerr.db.migrations import ALEMBIC_DIR, current_revision

router = APIRouter()


def _head_revision(script_location: Path = ALEMBIC_DIR) -> str | None:
    """The migration head known to this build (no DB access)."""
    cfg = Config()
    cfg.set_main_option("script_location", str(script_location))
    return ScriptDirectory.from_config(cfg).get_current_head()


def _migration_health(db_path: Path) -> dict[str, Any]:
    try:
        head = _head_revision()
        current = current_revision(db_path)
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


@router.get("/health", include_in_schema=False)
async def health(request: Request, response: Response) -> dict[str, Any]:
    app = request.app
    db = app.state.db
    commands = app.state.commands
    scheduler = app.state.scheduler

    components = {
        "database": await db.health(),
        "workers": commands.health(),
        "scheduler": await _scheduler_health(scheduler),
        "migrations": _migration_health(db.db_path),
    }
    failing = [name for name, comp in components.items() if comp.get("status") != "up"]
    body = {"status": "up" if not failing else "down", "components": components}
    if failing:
        response.status_code = 503
    return body
