"""Source row + entitlement persistence and settings (de)serialization
(FRG-SRC-001/002/003).

Settings (de)serialization REUSES the generic keystore-aware helpers the indexer
area already owns (:mod:`foragerr.indexers.repo`) rather than duplicating them —
``serialize_settings`` / ``_decrypt_payload`` / ``register_row_secrets`` /
``public_settings`` are provider-agnostic (they key off the settings model's
TOP-LEVEL ``SecretStr`` fields), so the Humble cookie is encrypted at rest,
redacted, and write-only with no source-specific crypto code. Only the
*validation* step is source-specific (the source-type registry).
"""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel
from sqlalchemy import select

from foragerr.db.base import utcnow
# Reuse the generic (provider-agnostic) keystore-aware settings helpers.
from foragerr.indexers.repo import (
    _decrypt_payload,
    public_settings,
    register_row_secrets,
    serialize_settings,
)
from foragerr.sources.models import SourceEntitlementRow, SourceRow
from foragerr.sources.registry import validate_settings

logger = logging.getLogger("foragerr.sources.repo")

__all__ = [
    "create_source",
    "delete_source",
    "get_source",
    "list_sources",
    "load_source_settings",
    "public_settings",
    "serialize_settings",
    "set_connection_state",
    "update_source_settings",
]


def load_source_settings(source_type: str, settings_json: str) -> BaseModel:
    """Parse + validate a source row's settings JSON, decrypting the cookie and
    registering it for redaction (FRG-SRC-002). Raises on unknown type, invalid
    payload, or a secret that fails to decrypt (FRG-AUTH-012)."""
    payload = _decrypt_payload(json.loads(settings_json))
    model = validate_settings(source_type, payload)
    register_row_secrets(model)
    return model


async def create_source(
    db,
    *,
    source_type: str,
    name: str,
    settings: BaseModel,
    connection_state: str = "connected",
    auto_sync: bool = False,
) -> SourceRow:
    """Persist a validated source as one ``sources`` row (FRG-SRC-001)."""
    register_row_secrets(settings)
    now = utcnow()
    async with db.write_session() as session:
        row = SourceRow(
            type=source_type,
            name=name,
            settings=serialize_settings(settings),
            connection_state=connection_state,
            auto_sync=auto_sync,
            added_at=now,
        )
        session.add(row)
        await session.flush()
        session.expunge(row)
    return row


async def get_source(db, source_id: int) -> SourceRow | None:
    """Load one source row by id (detached), or ``None``."""
    async with db.read_session() as session:
        row = await session.get(SourceRow, source_id)
        if row is not None:
            session.expunge(row)
        return row


async def list_sources(db) -> list[SourceRow]:
    """Every configured source (detached), newest-first by id."""
    async with db.read_session() as session:
        rows = (
            (await session.execute(select(SourceRow).order_by(SourceRow.id)))
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
        return list(rows)


async def update_source_settings(
    db, source_id: int, *, settings: BaseModel, connection_state: str
) -> SourceRow | None:
    """Replace a source's settings (re-encrypted) and connection state — the
    reconnect path (FRG-SRC-005). Returns the detached row or ``None``."""
    register_row_secrets(settings)
    async with db.write_session() as session:
        row = await session.get(SourceRow, source_id)
        if row is None:
            return None
        row.settings = serialize_settings(settings)
        row.connection_state = connection_state
        await session.flush()
        session.expunge(row)
        return row


async def set_connection_state(
    db, source_id: int, state: str, *, clear_credential: bool = False
) -> SourceRow | None:
    """Transition a source's connection state (FRG-SRC-001/005).

    ``clear_credential`` (disconnect) blanks the stored settings JSON so the
    encrypted cookie is deleted, while every entitlement row is left untouched
    (FRG-SRC-001 "disconnect keeps synced data"). Returns the detached row."""
    async with db.write_session() as session:
        row = await session.get(SourceRow, source_id)
        if row is None:
            return None
        row.connection_state = state
        if clear_credential:
            row.settings = "{}"
        await session.flush()
        session.expunge(row)
        return row


async def delete_source(db, source_id: int) -> bool:
    """Delete one source row and (via cascade) its entitlements. ``True`` if a
    row was removed. NOTE: disconnect (state change) is the data-preserving path;
    this hard delete is for an operator explicitly removing a source entirely."""
    async with db.write_session() as session:
        row = await session.get(SourceRow, source_id)
        if row is None:
            return False
        await session.delete(row)
        return True
