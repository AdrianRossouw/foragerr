"""Health aggregation area (FRG-NFR-011 / FRG-API-014).

One :class:`~foragerr.health.service.HealthService` composes per-component
health from already-persisted or cheap-live state (provider back-off, database
integrity, filesystem free space, scheduler status) and derives both the
per-component view (``/api/v1/system/health``) and the warnings subset
(``/api/v1/health``). The database-integrity component reads a small in-memory
result written by the startup ``quick_check`` and the pre-backup
``integrity_check`` (``foragerr.health.state``) — no new tracking table.
"""

from __future__ import annotations

from foragerr.health.service import (
    ComponentHealth,
    HealthService,
    HealthWarning,
)
from foragerr.health.state import (
    DatabaseIntegrityState,
    current_integrity,
    record_integrity,
    reset_integrity,
)

__all__ = [
    "ComponentHealth",
    "DatabaseIntegrityState",
    "HealthService",
    "HealthWarning",
    "current_integrity",
    "record_integrity",
    "reset_integrity",
]
