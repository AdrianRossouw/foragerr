"""System status, health, and scheduled-task transport (FRG-API-014).

Extends the original version/build-info endpoint (FRG-DEP-009, FRG-DEP-010)
with the m2-ops-health-backups delta: runtime + managed-path fields on
``GET /system/status`` (never a secret), the health-warnings list
(``GET /health``, distinct from the root DEP liveness probe), the
per-component health view (``GET /system/health``, FRG-NFR-011), and the
scheduled-task list + force-run (``GET``/``POST /system/task*``,
FRG-SCHED-007). Health/task state is READ from the sched/health areas'
services, never re-implemented here (this module owns aggregation +
transport only).

Version, commit, and build date are resolved once per process and never
change while it runs (FRG-DEP-009: no self-update, no in-place version
change). Commit/build-date are env-injected at image build time
(``FORAGERR_BUILD_COMMIT``/``FORAGERR_BUILD_DATE``); outside a built
artifact (local ``uv run uvicorn``) they fall back to well-defined
placeholders rather than erroring or omitting the fields.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import platform
import time

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from foragerr.api.command import CommandResource
from foragerr.api.errors import ApiError
from foragerr.commands import UnknownTaskError
from foragerr.db.backup import BACKUPS_DIRNAME
from foragerr.db.engine import database_path
from foragerr.db.migrations import app_version
from foragerr.health.service import ComponentHealth, health_service_from_app
from foragerr.library.models import RootFolderRow

logger = logging.getLogger("foragerr.system")

router = APIRouter(tags=["system"])

_UNKNOWN = "unknown"


class _BuildInfo(BaseModel):
    """Version/commit/build-date trio (FRG-DEP-010) — internal helper shape."""

    version: str
    commit: str
    build_date: str


class SystemStatus(BaseModel):
    """``GET /api/v1/system/status`` response (FRG-DEP-010, extended FRG-API-014).

    The original ``{version, commit, build_date}`` trio stays byte-for-byte;
    the fields below are additive. Only directory paths, a count, and
    process/runtime metadata are exposed here — NEVER a provider key,
    credential, or other secret value.
    """

    version: str
    commit: str
    build_date: str
    config_dir: str
    db_path: str
    backups_dir: str
    root_folder_count: int
    uptime_seconds: float
    python_version: str
    os: str


class HealthWarningItem(BaseModel):
    """One ``GET /api/v1/health`` warnings-list entry (FRG-API-014).

    ``remediation_hint`` serializes as ``remediationHint`` — the delta spec's
    literal contract note, even though most other envelopes in this API are
    snake_case (design decision 5).
    """

    model_config = ConfigDict(populate_by_name=True)

    source: str
    type: str
    message: str
    remediation_hint: str | None = Field(default=None, alias="remediationHint")


class SystemHealthComponent(BaseModel):
    """One ``GET /api/v1/system/health`` per-component row (FRG-NFR-011)."""

    component: str
    state: str
    message: str | None
    last_success: dt.datetime | None
    last_failure: dt.datetime | None
    disabled_until: dt.datetime | None

    @classmethod
    def from_domain(cls, component: ComponentHealth) -> "SystemHealthComponent":
        return cls(
            component=component.component,
            state=component.state,
            message=component.message,
            last_success=component.last_success,
            last_failure=component.last_failure,
            disabled_until=component.disabled_until,
        )


class ScheduledTask(BaseModel):
    """One ``GET /api/v1/system/task`` row: ``scheduler.status()`` enriched
    with the command name + a display label (design decision 8)."""

    name: str
    command_name: str
    label: str
    interval_seconds: int
    last_run: dt.datetime | None
    next_run: dt.datetime | None


def _task_label(name: str) -> str:
    """A Sonarr-shaped display label derived from the task name."""
    return name.replace("-", " ").replace("_", " ").title()


def build_info() -> _BuildInfo:
    """Resolve version/commit/build-date with dev/unknown fallbacks."""
    return _BuildInfo(
        version=app_version(),
        commit=os.environ.get("FORAGERR_BUILD_COMMIT", _UNKNOWN),
        build_date=os.environ.get("FORAGERR_BUILD_DATE", _UNKNOWN),
    )


def log_startup_version() -> None:
    """Early startup log line carrying the same version info the API
    reports (FRG-DEP-010)."""
    info = build_info()
    logger.info(
        "foragerr starting: version=%s commit=%s build_date=%s",
        info.version,
        info.commit,
        info.build_date,
    )


@router.get("/system/status", response_model=SystemStatus)
async def system_status(request: Request) -> SystemStatus:
    app = request.app
    settings = app.state.settings
    info = build_info()

    config_dir = settings.config_dir
    db_path = database_path(config_dir)
    backups_dir = config_dir / BACKUPS_DIRNAME

    started_at = getattr(app.state, "process_started_at", None)
    uptime_seconds = (
        time.monotonic() - started_at if started_at is not None else 0.0
    )

    db = app.state.db
    async with db.read_session() as session:
        root_folder_count = await session.scalar(
            select(func.count()).select_from(RootFolderRow)
        )

    return SystemStatus(
        version=info.version,
        commit=info.commit,
        build_date=info.build_date,
        config_dir=str(config_dir),
        db_path=str(db_path),
        backups_dir=str(backups_dir),
        root_folder_count=root_folder_count or 0,
        uptime_seconds=uptime_seconds,
        python_version=platform.python_version(),
        os=platform.system(),
    )


@router.get("/health", response_model=list[HealthWarningItem])
async def health_warnings(request: Request) -> list[HealthWarningItem]:
    """The actionable health-warnings list (FRG-API-014), distinct from the
    root, unauthenticated ``GET /health`` liveness probe (untouched, DEP)."""
    service = health_service_from_app(request.app)
    warnings = await service.warnings()
    return [
        HealthWarningItem(
            source=warning.source,
            type=warning.type,
            message=warning.message,
            remediation_hint=warning.remediation_hint,
        )
        for warning in warnings
    ]


@router.get("/system/health", response_model=list[SystemHealthComponent])
async def system_health(request: Request) -> list[SystemHealthComponent]:
    """The full per-component health view (FRG-NFR-011)."""
    service = health_service_from_app(request.app)
    components = await service.component_view()
    return [SystemHealthComponent.from_domain(c) for c in components]


@router.get("/system/task", response_model=list[ScheduledTask])
async def list_tasks(request: Request) -> list[ScheduledTask]:
    """Scheduled tasks with schedule state and the command each runs."""
    scheduler = request.app.state.scheduler
    rows = await scheduler.status()
    tasks: list[ScheduledTask] = []
    for row in rows:
        definition = scheduler.task_definition(row["name"])
        tasks.append(
            ScheduledTask(
                name=row["name"],
                command_name=definition.command_name,
                label=_task_label(row["name"]),
                interval_seconds=row["interval_seconds"],
                last_run=row["last_run"],
                next_run=row["next_run"],
            )
        )
    return tasks


@router.post("/system/task/{name}", response_model=CommandResource, status_code=202)
async def force_run_task(name: str, request: Request) -> CommandResource:
    """Force-run a scheduled task (FRG-SCHED-007): enqueues its command now,
    resets the timer, dedups, and returns the enqueued command so the client
    can track it to terminal. Unknown task name -> 404."""
    scheduler = request.app.state.scheduler
    try:
        record = await scheduler.force_run(name)
    except UnknownTaskError as exc:
        raise ApiError(404, f"scheduled task {name!r} not found") from exc
    return CommandResource.from_record(record)
