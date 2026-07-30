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
from dataclasses import dataclass

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
    "ProposalAttempt",
    "clear_publisher_rules",
    "create_source",
    "delete_source",
    "get_entitlement",
    "get_source",
    "list_entitlements",
    "list_sources",
    "load_source_settings",
    "public_settings",
    "record_proposal_attempts",
    "serialize_settings",
    "set_auto_sync",
    "set_connection_state",
    "update_source_settings",
]


async def get_entitlement(db, entitlement_id: int) -> SourceEntitlementRow | None:
    """Load one entitlement row by id (detached), or ``None`` (FRG-SRC-004)."""
    async with db.read_session() as session:
        row = await session.get(SourceEntitlementRow, entitlement_id)
        if row is not None:
            session.expunge(row)
        return row


async def list_entitlements(
    db,
    source_id: int,
    *,
    classification: str | None = None,
    review_status: str | None = None,
    order_by_attempt: bool = False,
) -> list[SourceEntitlementRow]:
    """Entitlements of one source (detached), optionally filtered by the
    classification and/or review-status axes (FRG-SRC-004), oldest-first.

    ``order_by_attempt`` switches the ordering to the proposal-work order
    (FRG-SRC-013): never-attempted rows first (``proposal_attempted_at`` NULL),
    then oldest attempt first, with the row id as a stable tiebreak. That is the
    ordering that makes a proposal pass CONVERGE — a row that fails or defers
    stamps itself and therefore moves to the back, so it can only ever delay its
    own retry, never the first attempt of the rows behind it. The NULLs-first
    half is expressed explicitly rather than relying on the dialect's default
    NULL collation."""
    stmt = select(SourceEntitlementRow).where(
        SourceEntitlementRow.source_id == source_id
    )
    if classification is not None:
        stmt = stmt.where(SourceEntitlementRow.classification == classification)
    if review_status is not None:
        stmt = stmt.where(SourceEntitlementRow.review_status == review_status)
    if order_by_attempt:
        stmt = stmt.order_by(
            SourceEntitlementRow.proposal_attempted_at.is_(None).desc(),
            SourceEntitlementRow.proposal_attempted_at.asc(),
            SourceEntitlementRow.id,
        )
    else:
        stmt = stmt.order_by(SourceEntitlementRow.id)
    async with db.read_session() as session:
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            session.expunge(row)
        return list(rows)


@dataclass(frozen=True, slots=True)
class ProposalAttempt:
    """One row's outcome from a proposal-computing pass (FRG-SRC-013).

    Every attempt — whatever its outcome — stamps ``proposal_attempted_at``.
    Only the outcomes that produced a verdict carry ``store=True`` and write a
    proposal; a budget deferral and a ComicVine error stamp and nothing else, so
    the row keeps its NULL ``proposed_match_json`` and stays retryable exactly as
    FRG-SRC-010 requires.

    ``expect_json`` makes the write a compare-and-swap against the proposal the
    pass READ: it is applied only while the stored value is still that one. For
    ordinary enrichment ``expect_json`` is ``None`` (propose into an empty slot,
    the historical guard); for a revisit — a library-fallback marker re-run once
    a ComicVine key exists, a stale pre-universe proposal the bulk recompute is
    refreshing — it is the exact stale value being replaced. Either way a
    proposal that landed between the read and the write (a restore, the sibling
    sweep) is never clobbered by a value computed before it existed.
    """

    proposed_series_id: int | None = None
    proposed_match_json: str | None = None
    store: bool = False
    expect_json: str | None = None
    errored: bool = False


async def record_proposal_attempts(db, attempts: dict[int, ProposalAttempt]) -> int:
    """Stamp attempts (and write the proposals among them). Returns rows written.

    ONE write transaction for the whole pass (FRG-SRC-013). The review status is
    re-read per row inside it, so a row the operator matched or ignored while the
    pass was working keeps its decision — the pass only ever writes a proposal
    onto a row that is still ``new`` (FRG-SRC-008/012 stickiness).

    That re-read gates the attempt STAMP too, not just the proposal write. A
    decided row is not "out of the pending set anyway" from the row's point of
    view: matched and ignored rows are RESTORABLE, and a restore drops one back
    into ``new`` carrying whatever attempt bookkeeping it was left with. Stamping
    a row the operator decided mid-pass would hand it a fresh
    ``proposal_attempted_at`` it never earned — sending it to the back of the
    next run's work order — and, on an errored attempt, an
    ``proposal_attempt_error`` that makes the restored row sit out the retry
    spacing for something that happened before the operator touched it. The
    stamps exist to order work; work is only ever done on ``new`` rows, so only
    ``new`` rows are stamped.
    """
    if not attempts:
        return 0
    now = utcnow()
    written = 0
    async with db.write_session() as session:
        for eid, attempt in attempts.items():
            row = await session.get(SourceEntitlementRow, eid)
            if row is None:
                continue
            if row.review_status != "new":
                continue  # an operator decision landed mid-pass — leave it alone
            row.proposal_attempted_at = now
            row.proposal_attempt_error = attempt.errored
            if not attempt.store:
                continue
            if row.proposed_match_json != attempt.expect_json:
                continue  # the proposal changed under this pass — its value wins
            row.proposed_series_id = attempt.proposed_series_id
            row.proposed_match_json = attempt.proposed_match_json
            row.updated_at = now
            written += 1
    return written


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


async def clear_publisher_rules(db, source_id: int) -> bool:
    """Empty a source's superseded ``publisher_rules`` field in place, returning
    whether anything was written (FRG-SRC-012 migration).

    Read → merge → re-serialize inside ONE write transaction, and
    ``connection_state`` is not a parameter of it at all: the credential the
    envelope carries is re-encrypted on the way back, so a concurrent disconnect
    must not be able to interleave into a resurrected cookie or a restored
    connection state. A row whose envelope is blank or undecryptable carries no
    rules to clear and is left exactly as it is."""
    async with db.write_session() as session:
        row = await session.get(SourceRow, source_id)
        if row is None:
            return False
        try:
            model = load_source_settings(row.type, row.settings)
        except Exception:  # noqa: BLE001 — blank or undecryptable envelope
            return False
        if not getattr(model, "publisher_rules", None):
            return False
        updated = validate_settings(
            row.type, {**model.model_dump(), "publisher_rules": []}
        )
        register_row_secrets(updated)
        row.settings = serialize_settings(updated)
        await session.flush()
        return True


async def set_auto_sync(db, source_id: int, auto_sync: bool) -> SourceRow | None:
    """Flip a source's ``auto_sync`` toggle post-connect (FRG-SRC-004).

    Persists the flag only; it NEVER retroactively accepts existing entitlements
    — auto-accept happens exclusively during a subsequent sync's enrichment pass
    over newly discovered confident matches (``sources.enrich``). Returns the
    detached row, or ``None`` when the id is unknown."""
    async with db.write_session() as session:
        row = await session.get(SourceRow, source_id)
        if row is None:
            return None
        row.auto_sync = auto_sync
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
