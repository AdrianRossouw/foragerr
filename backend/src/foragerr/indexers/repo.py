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
import logging
from dataclasses import dataclass, field

from pydantic import BaseModel, SecretStr
from sqlalchemy import select

from foragerr.db.base import utcnow
from foragerr.indexers.models import USAGE_PATHS, IndexerRow
from foragerr.indexers.registry import get_implementation, validate_settings
from foragerr.logging import register_secret

logger = logging.getLogger("foragerr.indexers.repo")


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


#: Sentinel for :func:`update_indexer` — distinguishes "field omitted (keep the
#: stored value)" from an explicit ``None``, so a partial PUT only touches the
#: fields it actually carries (FRG-IDX-001/002).
_UNSET: object = object()


async def get_indexer(db, indexer_id: int) -> IndexerRow | None:
    """Load one indexer row by id (detached), or ``None`` (FRG-IDX-001)."""
    async with db.read_session() as session:
        row = await session.get(IndexerRow, indexer_id)
        if row is not None:
            session.expunge(row)
        return row


async def update_indexer(
    db,
    indexer_id: int,
    *,
    name: object = _UNSET,
    priority: object = _UNSET,
    enabled: object = _UNSET,
    enable_rss: object = _UNSET,
    enable_auto: object = _UNSET,
    enable_interactive: object = _UNSET,
    settings: object = _UNSET,
) -> IndexerRow | None:
    """Partially update an indexer row (FRG-IDX-001/002); omitted kwargs are
    left untouched. ``settings`` (when given) is an already-validated settings
    model — the caller is responsible for merging omitted secret keys onto the
    stored value BEFORE validating, so a write-only secret survives an edit that
    doesn't resupply it (FRG-API-009). Returns the detached row, or ``None`` if
    no such indexer exists."""
    async with db.write_session() as session:
        row = await session.get(IndexerRow, indexer_id)
        if row is None:
            return None
        if name is not _UNSET:
            row.name = name  # type: ignore[assignment]
        if priority is not _UNSET:
            row.priority = priority  # type: ignore[assignment]
        if enabled is not _UNSET:
            row.enabled = enabled  # type: ignore[assignment]
        if enable_rss is not _UNSET:
            row.enable_rss = enable_rss  # type: ignore[assignment]
        if enable_auto is not _UNSET:
            row.enable_auto = enable_auto  # type: ignore[assignment]
        if enable_interactive is not _UNSET:
            row.enable_interactive = enable_interactive  # type: ignore[assignment]
        if settings is not _UNSET:
            register_row_secrets(settings)  # type: ignore[arg-type]
            row.settings = serialize_settings(settings)  # type: ignore[arg-type]
        await session.flush()
        session.expunge(row)
        return row


async def delete_indexer(db, indexer_id: int) -> bool:
    """Delete one indexer row (FRG-IDX-001). ``True`` if a row was removed."""
    async with db.write_session() as session:
        row = await session.get(IndexerRow, indexer_id)
        if row is None:
            return False
        await session.delete(row)
        return True


@dataclass(frozen=True, slots=True)
class IndexerListing:
    """The result of loading every indexer with per-row settings validation.

    ``healthy`` rows have valid, secret-registered settings and are safe to
    search. ``failed`` rows are those whose settings JSON could not load (a
    corrupt/incompatible row); they are isolated here so ONE bad row can never
    abort the whole batch (FRG-NFR-010) — the caller surfaces them as failed
    per-indexer outcomes rather than searching them.
    """

    healthy: list[IndexerRow] = field(default_factory=list)
    failed: list[IndexerRow] = field(default_factory=list)


async def load_indexers(db) -> IndexerListing:
    """Load all indexers, validating each row's settings in isolation.

    A row whose settings fail to load is skipped with a structured warning
    (naming the indexer) and reported as ``failed`` rather than raising and
    wedging every healthy indexer in the same search (FRG-NFR-010)."""
    async with db.read_session() as session:
        rows = (await session.execute(select(IndexerRow))).scalars().all()
        for row in rows:
            session.expunge(row)
    healthy: list[IndexerRow] = []
    failed: list[IndexerRow] = []
    for row in rows:
        try:
            load_settings(row.implementation, row.settings)  # redaction re-register
        except Exception as exc:  # noqa: BLE001 — isolate one corrupt row
            logger.warning(
                "indexer settings failed to load; skipping this indexer",
                extra={"indexer_id": row.id, "indexer_name": row.name, "error": str(exc)},
            )
            failed.append(row)
            continue
        healthy.append(row)
    return IndexerListing(healthy=healthy, failed=failed)


async def list_indexers(db) -> list[IndexerRow]:
    """All configured, loadable indexers, each with its secrets re-registered.

    A thin wrapper over :func:`load_indexers` returning only the healthy rows
    (corrupt rows are skipped and logged, never fatal)."""
    return (await load_indexers(db)).healthy


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
