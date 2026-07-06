"""The health-aggregation service (FRG-NFR-011).

One service composes a per-component health list from already-persisted or
cheap-live state and derives BOTH shapes the API surface needs from that single
list, so they can never disagree (FRG-NFR-011 scenario 3):

- :meth:`HealthService.component_view` — every tracked component with its state
  and last-success/last-failure timestamps (``GET /api/v1/system/health``).
- :meth:`HealthService.warnings` — exactly the non-ok subset, each carrying a
  remediation hint (``GET /api/v1/health``, FRG-API-014).

Components:

- **ComicVine** — the process rate-limiter's degraded flag
  (``metadata/ratelimit.comicvine_health``).
- **each indexer / download client / DDL provider** — enumerated from their
  tables and overlaid with :meth:`ProviderBackoff.health` state (a configured
  provider with no back-off row is ``ok``); the checks are owned by those areas
  and only READ here.
- **scheduler** — ``scheduler.status()`` succeeding (mirrors the DEP probe).
- **database** — the in-memory integrity reading (``health.state``) plus the
  age of the newest scheduled backup (a filesystem read — no tracking table).
- **root folders** — existence, writability, and free space per configured root.
- **disk space** — free space on the config volume under a documented floor.

Reads offload blocking filesystem stats to threads so a wedged mount never
freezes the event loop.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select

from foragerr.config import Settings
from foragerr.db import Database, utcnow
from foragerr.db.backup import latest_scheduled_backup
from foragerr.downloads.models import DownloadClientRow
from foragerr.health.state import current_integrity
from foragerr.indexers.models import IndexerRow
from foragerr.library.models import RootFolderRow
from foragerr.metadata.ratelimit import comicvine_health
from foragerr.providers.backoff import (
    PROVIDER_DDL,
    PROVIDER_DOWNLOAD_CLIENT,
    PROVIDER_INDEXER,
    BackoffStatus,
    ProviderBackoff,
)

logger = logging.getLogger("foragerr.health.service")

#: Free-space floor below which a volume is flagged (design open question 2:
#: a small absolute floor; promote to a config key only if it proves noisy).
LOW_DISK_FLOOR_BYTES = 1 * 1024**3  # 1 GiB

#: Deadline for a single offloaded filesystem probe (root-folder / disk stat).
#: A wedged network mount would otherwise hang the health request and pile
#: blocked threads into the shared executor; the timeout bounds the REQUEST.
#: NOTE: the blocked worker thread itself cannot be cancelled (an inherent limit
#: of ``to_thread``); this only stops the request from waiting on it.
FS_PROBE_TIMEOUT_SECONDS = 5.0

#: A scheduled backup older than this multiple of the configured interval is
#: surfaced as an overdue-backup warning on the database component.
BACKUP_OVERDUE_INTERVAL_MULTIPLE = 2

_STATE_OK = "ok"
_STATE_DEGRADED = "degraded"
_STATE_ERROR = "error"


@dataclass(frozen=True)
class ComponentHealth:
    """One component's health for the per-component view (FRG-NFR-011)."""

    component: str  # stable id, e.g. "database", "indexer:3"
    kind: str  # comicvine|indexer|download_client|ddl|scheduler|database|root_folder|disk
    label: str  # display name
    state: str  # ok|degraded|error
    message: str | None = None
    remediation: str | None = None
    last_success: dt.datetime | None = None
    last_failure: dt.datetime | None = None
    disabled_until: dt.datetime | None = None

    @property
    def ok(self) -> bool:
        return self.state == _STATE_OK


@dataclass(frozen=True)
class HealthWarning:
    """One actionable warning for the warnings list (FRG-API-014)."""

    source: str
    type: str  # warning|error
    message: str
    remediation_hint: str | None = None


def _warning_type(state: str) -> str:
    return _STATE_ERROR if state == _STATE_ERROR else "warning"


class HealthService:
    """Compose component health from persisted / cheap-live state.

    ``scheduler`` is optional so the service is unit-testable without the full
    app; when omitted the scheduler component is reported as an error (its loop
    is not observable).
    """

    def __init__(
        self,
        db: Database,
        settings: Settings,
        *,
        scheduler: Any | None = None,
        clock=utcnow,
    ) -> None:
        self._db = db
        self._settings = settings
        self._scheduler = scheduler
        self._clock = clock
        self._backoff = ProviderBackoff(db)

    async def component_view(self) -> list[ComponentHealth]:
        """Every tracked component with state + timestamps (one aggregation).

        Each producer is isolated: one raising check becomes an error-state
        component instead of 500-ing the whole endpoint, so a single broken
        signal never hides every other component's health.
        """
        components: list[ComponentHealth] = []
        components += await self._safe(
            lambda: self._comicvine_component(),
            component="comicvine",
            kind="comicvine",
            label="ComicVine",
        )
        components += await self._safe(
            lambda: self._provider_components(),
            component="providers",
            kind="provider",
            label="Providers",
        )
        components += await self._safe(
            lambda: self._scheduler_component(),
            component="scheduler",
            kind="scheduler",
            label="Scheduler",
        )
        components += await self._safe(
            lambda: self._database_component(),
            component="database",
            kind="database",
            label="Database",
        )
        components += await self._safe(
            lambda: self._root_folder_components(),
            component="root-folders",
            kind="root_folder",
            label="Root folders",
        )
        components += await self._safe(
            lambda: self._disk_component(),
            component="disk-space",
            kind="disk",
            label="Config volume free space",
        )
        return components

    async def _safe(
        self, produce, *, component: str, kind: str, label: str
    ) -> list[ComponentHealth]:
        """Run one component producer, converting any raise into an error item.

        ``produce`` may return a single :class:`ComponentHealth`, a list of them,
        or a coroutine yielding either. A raised exception is logged (with the
        traceback) and reported as one error-state component so the rest of the
        view still renders and the endpoint stays 200.
        """
        try:
            result = produce()
            if asyncio.iscoroutine(result):
                result = await result
            return list(result) if isinstance(result, list) else [result]
        except Exception as exc:  # noqa: BLE001 - isolation is the whole point
            logger.exception("health: component %s check raised", component)
            return [
                ComponentHealth(
                    component=component,
                    kind=kind,
                    label=label,
                    state=_STATE_ERROR,
                    message=f"health check failed: {type(exc).__name__}",
                    remediation=(
                        "This health check raised an error; see the server logs "
                        "for the traceback."
                    ),
                )
            ]

    async def warnings(self) -> list[HealthWarning]:
        """The non-ok subset of :meth:`component_view`, with remediation hints."""
        return [
            HealthWarning(
                source=comp.component,
                type=_warning_type(comp.state),
                message=comp.message or comp.label,
                remediation_hint=comp.remediation,
            )
            for comp in await self.component_view()
            if not comp.ok
        ]

    # -- components ----------------------------------------------------------

    def _comicvine_component(self) -> ComponentHealth:
        health = comicvine_health()
        if health.get("degraded"):
            remaining = float(health.get("cooldown_remaining_seconds", 0.0) or 0.0)
            return ComponentHealth(
                component="comicvine",
                kind="comicvine",
                label="ComicVine",
                state=_STATE_DEGRADED,
                message=(
                    f"ComicVine is rate-limited/backed off "
                    f"(~{remaining:.0f}s cool-down remaining)"
                ),
                remediation=(
                    "Recovers automatically as the rate limit clears; if it "
                    "persists, verify the ComicVine API key and connectivity."
                ),
            )
        return ComponentHealth(
            component="comicvine", kind="comicvine", label="ComicVine", state=_STATE_OK
        )

    async def _provider_components(self) -> list[ComponentHealth]:
        # One read of the back-off table for the tracked (failed) providers, then
        # overlay onto the enumerated configured providers (no row == ok).
        statuses = await self._backoff.health()
        by_key = {(s.provider_type, s.provider_id): s for s in statuses}

        async with self._db.read_session() as session:
            indexers = (
                (await session.execute(select(IndexerRow).order_by(IndexerRow.id)))
                .scalars()
                .all()
            )
            clients = (
                (
                    await session.execute(
                        select(DownloadClientRow).order_by(DownloadClientRow.id)
                    )
                )
                .scalars()
                .all()
            )

        components: list[ComponentHealth] = []
        for row in indexers:
            components.append(
                self._provider_component(
                    kind="indexer",
                    label=f"Indexer: {row.name}",
                    component=f"indexer:{row.id}",
                    status=by_key.get((PROVIDER_INDEXER, row.id)),
                    remediation=(
                        f"Indexer '{row.name}' is in failure back-off; verify its "
                        "URL and API key."
                    ),
                )
            )
        for row in clients:
            is_ddl = row.implementation == "ddl"
            provider_type = PROVIDER_DDL if is_ddl else PROVIDER_DOWNLOAD_CLIENT
            components.append(
                self._provider_component(
                    kind="ddl" if is_ddl else "download_client",
                    label=(f"DDL provider: {row.name}" if is_ddl else f"Download client: {row.name}"),
                    component=f"{'ddl' if is_ddl else 'download-client'}:{row.id}",
                    status=by_key.get((provider_type, row.id)),
                    remediation=(
                        f"'{row.name}' is in failure back-off; verify its host, "
                        "port, and API key/connectivity."
                    ),
                )
            )
        return components

    def _provider_component(
        self,
        *,
        kind: str,
        label: str,
        component: str,
        status: BackoffStatus | None,
        remediation: str,
    ) -> ComponentHealth:
        if status is None or status.healthy:
            return ComponentHealth(
                component=component, kind=kind, label=label, state=_STATE_OK
            )
        disabled_until = status.next_allowed_at if status.active else None
        reason = f": {status.last_reason}" if status.last_reason else ""
        message = (
            f"{label} is backed off after {status.failure_count} failure(s){reason}"
        )
        if disabled_until is not None:
            message += f"; disabled until {disabled_until.isoformat()}"
        return ComponentHealth(
            component=component,
            kind=kind,
            label=label,
            state=_STATE_DEGRADED,
            message=message,
            remediation=remediation,
            last_failure=status.last_failure_at,
            disabled_until=disabled_until,
        )

    async def _scheduler_component(self) -> ComponentHealth:
        label = "Scheduler"
        if self._scheduler is None:
            return ComponentHealth(
                component="scheduler",
                kind="scheduler",
                label=label,
                state=_STATE_ERROR,
                message="Scheduler is not available",
                remediation="Restart the container; the task loop is not running.",
            )
        try:
            await self._scheduler.status()
        except Exception as exc:  # noqa: BLE001 - a failed probe is the signal
            return ComponentHealth(
                component="scheduler",
                kind="scheduler",
                label=label,
                state=_STATE_ERROR,
                message=f"Scheduler status probe failed: {exc}",
                remediation="Restart the container; the task loop is not running.",
            )
        return ComponentHealth(
            component="scheduler", kind="scheduler", label=label, state=_STATE_OK
        )

    async def _database_component(self) -> ComponentHealth:
        label = "Database"
        integrity = current_integrity()
        if integrity is not None and not integrity.ok:
            return ComponentHealth(
                component="database",
                kind="database",
                label=label,
                state=_STATE_ERROR,
                message=f"Integrity check failed — {integrity.detail}",
                remediation=(
                    "The database failed its integrity check. Stop the container "
                    "and restore the most recent good backup (see the manual)."
                ),
                last_failure=integrity.checked_at,
            )

        last_success = integrity.checked_at if integrity is not None else None
        # Backup freshness (FRG-NFR-011): a missing or overdue scheduled backup
        # is a warning on the database component.
        config_dir = self._settings.config_dir
        latest = await asyncio.to_thread(latest_scheduled_backup, config_dir)
        now = self._clock()
        if latest is None:
            return ComponentHealth(
                component="database",
                kind="database",
                label=label,
                state=_STATE_DEGRADED,
                message="No scheduled database backup has been taken yet",
                remediation=(
                    "Run the 'backup-database' task (System → Tasks → Back up now) "
                    "or wait for its next scheduled run."
                ),
                last_success=last_success,
            )
        mtime = await asyncio.to_thread(lambda: latest.stat().st_mtime)
        mtime_utc = dt.datetime.fromtimestamp(mtime, dt.timezone.utc).replace(
            tzinfo=None
        )
        age = now - mtime_utc
        overdue = dt.timedelta(
            seconds=self._settings.db_backup_interval_seconds
            * BACKUP_OVERDUE_INTERVAL_MULTIPLE
        )
        if age > overdue:
            return ComponentHealth(
                component="database",
                kind="database",
                label=label,
                state=_STATE_DEGRADED,
                message=(
                    f"Latest scheduled backup is overdue "
                    f"({int(age.total_seconds() // 3600)}h old)"
                ),
                remediation=(
                    "Check the 'backup-database' task and free disk space; run "
                    "'Back up now' to refresh the rolling backup."
                ),
                last_success=last_success,
            )
        return ComponentHealth(
            component="database",
            kind="database",
            label=label,
            state=_STATE_OK,
            last_success=last_success,
        )

    async def _root_folder_components(self) -> list[ComponentHealth]:
        async with self._db.read_session() as session:
            rows = (
                (await session.execute(select(RootFolderRow).order_by(RootFolderRow.id)))
                .scalars()
                .all()
            )
        components: list[ComponentHealth] = []
        for row in rows:
            components.append(await self._root_folder_component(row.id, row.path))
        return components

    async def _root_folder_component(self, rid: int, path: str) -> ComponentHealth:
        component = f"root-folder:{rid}"
        label = f"Root folder: {path}"
        try:
            exists, writable, free = await asyncio.wait_for(
                asyncio.to_thread(self._probe_path, path), FS_PROBE_TIMEOUT_SECONDS
            )
        except (asyncio.TimeoutError, TimeoutError):
            # A wedged mount: unreachable is an error for a root folder (its
            # media cannot be read/written). The orphaned probe thread lives on.
            return ComponentHealth(
                component=component,
                kind="root_folder",
                label=label,
                state=_STATE_ERROR,
                message=f"Root folder '{path}' is unreachable (timed out)",
                remediation="Check the volume mount; the path did not respond.",
            )
        if not exists:
            return ComponentHealth(
                component=component,
                kind="root_folder",
                label=label,
                state=_STATE_ERROR,
                message=f"Root folder '{path}' is missing or unreadable",
                remediation="Check the volume mount and permissions for this path.",
            )
        if not writable:
            return ComponentHealth(
                component=component,
                kind="root_folder",
                label=label,
                state=_STATE_ERROR,
                message=f"Root folder '{path}' is not writable",
                remediation="Fix the ownership/permissions (PUID/PGID) on this path.",
            )
        if free is not None and free < LOW_DISK_FLOOR_BYTES:
            return ComponentHealth(
                component=component,
                kind="root_folder",
                label=label,
                state=_STATE_DEGRADED,
                message=f"Root folder '{path}' is low on free space ({_gib(free)} GiB)",
                remediation="Free space or add capacity on this volume.",
            )
        return ComponentHealth(
            component=component, kind="root_folder", label=label, state=_STATE_OK
        )

    async def _disk_component(self) -> ComponentHealth:
        config_dir = str(self._settings.config_dir)
        component = "disk-space"
        label = "Config volume free space"
        try:
            free = await asyncio.wait_for(
                asyncio.to_thread(self._free_space, config_dir),
                FS_PROBE_TIMEOUT_SECONDS,
            )
        except (asyncio.TimeoutError, TimeoutError):
            return ComponentHealth(
                component=component,
                kind="disk",
                label=label,
                state=_STATE_ERROR,
                message=f"Config volume ({config_dir}) is unreachable (timed out)",
                remediation="Check the /config mount; the volume did not respond.",
            )
        if free is None:
            return ComponentHealth(
                component=component,
                kind="disk",
                label=label,
                state=_STATE_ERROR,
                message=f"Cannot read free space on the config volume ({config_dir})",
                remediation="Check the /config mount.",
            )
        if free < LOW_DISK_FLOOR_BYTES:
            return ComponentHealth(
                component=component,
                kind="disk",
                label=label,
                state=_STATE_DEGRADED,
                message=(
                    f"Low free space on the config volume ({_gib(free)} GiB) — "
                    "database and backups live here"
                ),
                remediation="Free space or expand the /config volume.",
            )
        return ComponentHealth(
            component=component, kind="disk", label=label, state=_STATE_OK
        )

    # -- blocking probes (run via to_thread) ---------------------------------

    @staticmethod
    def _probe_path(path: str) -> tuple[bool, bool, int | None]:
        p = Path(path)
        if not p.exists():
            return (False, False, None)
        writable = os.access(path, os.W_OK)
        try:
            free = shutil.disk_usage(path).free
        except OSError:
            free = None
        return (True, writable, free)

    @staticmethod
    def _free_space(path: str) -> int | None:
        try:
            return shutil.disk_usage(path).free
        except OSError:
            return None


def _gib(nbytes: int) -> str:
    return f"{nbytes / 1024**3:.1f}"


def health_service_from_app(app: Any) -> HealthService:
    """Build a :class:`HealthService` from ``app.state`` (route convenience)."""
    return HealthService(
        app.state.db,
        app.state.settings,
        scheduler=getattr(app.state, "scheduler", None),
    )


__all__ = [
    "BACKUP_OVERDUE_INTERVAL_MULTIPLE",
    "ComponentHealth",
    "HealthService",
    "HealthWarning",
    "LOW_DISK_FLOOR_BYTES",
    "health_service_from_app",
]
