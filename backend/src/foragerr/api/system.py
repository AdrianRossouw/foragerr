"""Version/build-info endpoint and startup log line (FRG-DEP-009, FRG-DEP-010).

Version, commit, and build date are resolved once per process and never
change while it runs (FRG-DEP-009: no self-update, no in-place version
change). Commit/build-date are env-injected at image build time
(``FORAGERR_BUILD_COMMIT``/``FORAGERR_BUILD_DATE``); outside a built
artifact (local ``uv run uvicorn``) they fall back to well-defined
placeholders rather than erroring or omitting the fields.
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter
from pydantic import BaseModel

from foragerr.db.migrations import app_version

logger = logging.getLogger("foragerr.system")

router = APIRouter(tags=["system"])

_UNKNOWN = "unknown"


class SystemStatus(BaseModel):
    """``GET /api/v1/system/status`` response (FRG-DEP-010)."""

    version: str
    commit: str
    build_date: str


def build_info() -> SystemStatus:
    """Resolve version/commit/build-date with dev/unknown fallbacks."""
    return SystemStatus(
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
async def system_status() -> SystemStatus:
    return build_info()
