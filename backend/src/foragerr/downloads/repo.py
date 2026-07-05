"""Download-client row persistence + settings (de)serialization (FRG-DL-002/005).

Mirrors :mod:`foragerr.indexers.repo` and REUSES its generic settings helpers
(``serialize_settings`` / ``register_row_secrets`` / ``public_settings`` — all
plain functions over a Pydantic model) rather than forking them; only the
settings *validation* differs (it resolves the download-client registry). One
bad row can never abort loading the fleet — a row whose settings JSON fails to
load is isolated and surfaced as ``failed`` (FRG-NFR-010 parity).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from pydantic import BaseModel
from sqlalchemy import select

from foragerr.db.base import utcnow
from foragerr.downloads.models import DownloadClientRow, RemotePathMappingRow
from foragerr.downloads.pathmap import RemotePathMapping
from foragerr.downloads.registry import get_implementation, validate_settings
from foragerr.indexers.repo import (  # generic reuse — do not fork
    public_settings,
    register_row_secrets,
    serialize_settings,
)

logger = logging.getLogger("foragerr.downloads.repo")


def load_settings(implementation: str, settings_json: str) -> BaseModel:
    """Parse + validate a row's settings JSON, registering its secrets for
    redaction. Raises on unknown implementation or an invalid payload."""
    payload = json.loads(settings_json)
    model = validate_settings(implementation, payload)
    register_row_secrets(model)
    return model


async def create_download_client(
    db,
    *,
    name: str,
    implementation: str,
    settings: BaseModel,
    priority: int = 25,
    enabled: bool = True,
    remove_completed_downloads: bool = True,
) -> DownloadClientRow:
    """Persist a validated download client as one ``download_clients`` row."""
    impl = get_implementation(implementation)
    register_row_secrets(settings)
    now = utcnow()
    async with db.write_session() as session:
        row = DownloadClientRow(
            name=name,
            implementation=impl.name,
            protocol=impl.protocol,
            priority=priority,
            enabled=enabled,
            remove_completed_downloads=remove_completed_downloads,
            settings=serialize_settings(settings),
            added_at=now,
        )
        session.add(row)
        await session.flush()
        session.expunge(row)
    return row


#: Sentinel mirroring :data:`foragerr.indexers.repo._UNSET` — "field omitted
#: (keep stored value)" vs. an explicit ``None`` for a partial PUT (FRG-DL-002).
_UNSET: object = object()


async def get_download_client(db, client_id: int) -> DownloadClientRow | None:
    """Load one download-client row by id (detached), or ``None`` (FRG-DL-002)."""
    async with db.read_session() as session:
        row = await session.get(DownloadClientRow, client_id)
        if row is not None:
            session.expunge(row)
        return row


async def update_download_client(
    db,
    client_id: int,
    *,
    name: object = _UNSET,
    priority: object = _UNSET,
    enabled: object = _UNSET,
    remove_completed_downloads: object = _UNSET,
    settings: object = _UNSET,
) -> DownloadClientRow | None:
    """Partially update a download-client row (FRG-DL-002); omitted kwargs are
    left untouched. ``settings`` (when given) is an already-validated settings
    model with any omitted secret merged onto the stored value by the caller
    (write-only survival, FRG-API-009). Returns the detached row, or ``None``
    if no such client exists."""
    async with db.write_session() as session:
        row = await session.get(DownloadClientRow, client_id)
        if row is None:
            return None
        if name is not _UNSET:
            row.name = name  # type: ignore[assignment]
        if priority is not _UNSET:
            row.priority = priority  # type: ignore[assignment]
        if enabled is not _UNSET:
            row.enabled = enabled  # type: ignore[assignment]
        if remove_completed_downloads is not _UNSET:
            row.remove_completed_downloads = remove_completed_downloads  # type: ignore[assignment]
        if settings is not _UNSET:
            register_row_secrets(settings)  # type: ignore[arg-type]
            row.settings = serialize_settings(settings)  # type: ignore[arg-type]
        await session.flush()
        session.expunge(row)
        return row


async def delete_download_client(db, client_id: int) -> bool:
    """Delete one download-client row (FRG-DL-002). ``True`` if one was removed.

    The ``remote_path_mappings.client_id`` FK is ``ON DELETE CASCADE``, so a
    client's mappings are removed with it."""
    async with db.write_session() as session:
        row = await session.get(DownloadClientRow, client_id)
        if row is None:
            return False
        await session.delete(row)
        return True


@dataclass(frozen=True, slots=True)
class ClientListing:
    """Loaded download-client rows split into healthy vs. failed (FRG-NFR-010)."""

    healthy: list[DownloadClientRow] = field(default_factory=list)
    failed: list[DownloadClientRow] = field(default_factory=list)


async def load_download_clients(db) -> ClientListing:
    """Load all download clients, validating each row's settings in isolation.

    A row whose settings fail to load (or names an unknown implementation) is
    skipped with a structured warning and reported as ``failed`` rather than
    wedging the healthy clients.
    """
    async with db.read_session() as session:
        rows = (await session.execute(select(DownloadClientRow))).scalars().all()
        for row in rows:
            session.expunge(row)
    healthy: list[DownloadClientRow] = []
    failed: list[DownloadClientRow] = []
    for row in rows:
        try:
            load_settings(row.implementation, row.settings)  # redaction re-register
        except Exception as exc:  # noqa: BLE001 — isolate one corrupt row
            logger.warning(
                "download-client settings failed to load; skipping this client",
                extra={"client_id": row.id, "client_name": row.name, "error": str(exc)},
            )
            failed.append(row)
            continue
        healthy.append(row)
    return ClientListing(healthy=healthy, failed=failed)


async def list_download_clients(db) -> list[DownloadClientRow]:
    """All configured, loadable download clients (corrupt rows skipped)."""
    return (await load_download_clients(db)).healthy


async def load_mappings(db, client_id: int) -> list[RemotePathMapping]:
    """Load one client's remote-path mappings as domain objects (FRG-DL-005)."""
    async with db.read_session() as session:
        rows = (
            await session.execute(
                select(RemotePathMappingRow).where(
                    RemotePathMappingRow.client_id == client_id
                )
            )
        ).scalars().all()
        return [
            RemotePathMapping(
                host=row.host,
                remote_prefix=row.remote_path,
                local_prefix=row.local_path,
            )
            for row in rows
        ]


__all__ = [
    "ClientListing",
    "create_download_client",
    "delete_download_client",
    "get_download_client",
    "list_download_clients",
    "load_download_clients",
    "load_mappings",
    "load_settings",
    "public_settings",
    "update_download_client",
]
