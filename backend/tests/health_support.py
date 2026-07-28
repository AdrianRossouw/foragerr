"""Shared health-service test scaffolding (FRG-NFR-011 / FRG-DL-015).

The one no-op scheduler stub and Settings-backed :class:`HealthService`
factory used by the health-aggregation suite and the import-stall-memory
drain tests, so both exercise an identical quiet-by-default service instead
of two copies drifting apart.
"""

from __future__ import annotations

from foragerr.config import Settings
from foragerr.health import HealthService


class StubScheduler:
    async def status(self):  # pragma: no cover - health needs it to be quiet
        return []


def health_service(db, **settings_kw) -> HealthService:
    """A :class:`HealthService` over ``db`` with a quiet stub scheduler.

    ``settings_kw`` forwards to :class:`Settings` (e.g.
    ``import_stall_threshold_cycles``); ``config_dir`` is always the test
    database's own directory.
    """
    return HealthService(
        db,
        Settings(config_dir=db.db_path.parent, **settings_kw),
        scheduler=StubScheduler(),
    )
