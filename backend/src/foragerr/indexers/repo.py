"""Indexer row persistence + settings (de)serialization (FRG-IDX-001/002).

The settings JSON on an ``IndexerRow`` is the serialized settings model with
its ``SecretStr`` values revealed (so the indexer can actually authenticate).
On load the secret values re-register with the log-redaction filter, so an API
key persisted here is redacted everywhere it might later be logged
(FRG-IDX-001 scenario 3). Secret VALUES are never surfaced back out of a GET
(:func:`public_settings` drops them — write-only, FRG-API-009).
"""

from __future__ import annotations

import datetime as dt
import json

from pydantic import BaseModel, SecretStr
from sqlalchemy import select

from foragerr.db.base import utcnow
from foragerr.indexers.models import USAGE_PATHS, IndexerRow
from foragerr.indexers.registry import get_implementation, validate_settings
from foragerr.logging import register_secret


def serialize_settings(model: BaseModel) -> str:
    """Serialize a settings model to canonical JSON, revealing secret values
    so the persisted row can authenticate. Stored server-side only."""
    data: dict[str, object] = {}
    for name in type(model).model_fields:
        value = getattr(model, name)
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
        data[name] = value
    return json.dumps(data, sort_keys=True)


def load_settings(implementation: str, settings_json: str) -> BaseModel:
    """Parse + validate a row's settings JSON, registering its secrets for
    redaction. Raises on unknown implementation or an invalid payload."""
    payload = json.loads(settings_json)
    model = validate_settings(implementation, payload)
    register_row_secrets(model)
    return model


def register_row_secrets(model: BaseModel) -> None:
    """Register every ``SecretStr`` value in a settings model with the
    log-redaction filter (FRG-IDX-001 scenario 3)."""
    for name in type(model).model_fields:
        value = getattr(model, name)
        if isinstance(value, SecretStr):
            register_secret(value.get_secret_value())


def public_settings(model: BaseModel) -> dict[str, object]:
    """A settings view safe to return from a GET: secret fields dropped
    entirely (write-only), everything else passed through (FRG-API-009)."""
    out: dict[str, object] = {}
    for name in type(model).model_fields:
        value = getattr(model, name)
        if isinstance(value, SecretStr):
            continue  # write-only — never echoed
        out[name] = value
    return out


async def create_indexer(
    db,
    *,
    name: str,
    implementation: str,
    settings: BaseModel,
    priority: int = 25,
    enabled: bool = True,
    enable_rss: bool = True,
    enable_auto: bool = True,
    enable_interactive: bool = True,
    retention_override: int | None = None,
) -> IndexerRow:
    """Persist a validated indexer as one ``indexers`` row (FRG-IDX-001)."""
    impl = get_implementation(implementation)
    register_row_secrets(settings)
    now = utcnow()
    async with db.write_session() as session:
        row = IndexerRow(
            name=name,
            implementation=impl.name,
            protocol=impl.protocol,
            priority=priority,
            enabled=enabled,
            enable_rss=enable_rss,
            enable_auto=enable_auto,
            enable_interactive=enable_interactive,
            settings=serialize_settings(settings),
            retention_override=retention_override,
            added_at=now,
        )
        session.add(row)
        await session.flush()
        session.expunge(row)
    return row


async def list_indexers(db) -> list[IndexerRow]:
    """All configured indexers, each with its secrets re-registered."""
    async with db.read_session() as session:
        rows = (await session.execute(select(IndexerRow))).scalars().all()
        for row in rows:
            session.expunge(row)
    for row in rows:
        load_settings(row.implementation, row.settings)  # redaction re-register
    return list(rows)


def select_for_path(rows: list[IndexerRow], path: str) -> list[IndexerRow]:
    """Filter indexers to those an ``path``-family fetch may query: enabled AND
    the matching usage toggle on (FRG-IDX-002). ``path`` ∈ ``USAGE_PATHS``."""
    if path not in USAGE_PATHS:
        raise ValueError(f"unknown fetch path {path!r}; known: {USAGE_PATHS}")
    toggle = {
        "rss": "enable_rss",
        "auto": "enable_auto",
        "interactive": "enable_interactive",
    }[path]
    return [row for row in rows if row.enabled and getattr(row, toggle)]


def update_caps_snapshot(
    row: IndexerRow, *, caps_json: str, degraded: bool, at: dt.datetime | None = None
) -> None:
    """Record a caps-probe result on the row (mutates in place; the caller
    persists). Degraded probes are recorded, not fatal (FRG-IDX-004)."""
    row.caps_json = caps_json
    row.caps_degraded = degraded
    row.caps_fetched_at = at or utcnow()
