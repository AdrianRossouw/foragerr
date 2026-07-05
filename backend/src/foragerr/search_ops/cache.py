"""The interactive-search grab cache (FRG-SRCH-014 / FRG-API-008).

``GET /release`` runs a live search and caches each decided release keyed
``(indexer_id, guid)`` with a ~30 min expiry, so a later ``POST /release`` grabs
from the cache without re-searching — and returns a deterministic "search again"
error once the entry has expired (never a silent re-search). Rows live in the
``release_cache`` table (created by the indexers migration; owned here). A
scheduled prune drops expired rows so the cache cannot grow without bound.

The cached payload is exactly the grab hand-off (a :class:`GrabReleaseCommand`
``model_dump``): the POST needs no display fields, only what it takes to enqueue
the grab.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from typing import ClassVar, Literal

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from foragerr.commands.registry import BaseCommand, register_command, register_handler
from foragerr.commands.service import HandlerContext
from foragerr.db.base import utcnow
from foragerr.indexers.models import ReleaseCacheRow
from foragerr.search import Decision

from foragerr.search_ops.grab import GrabReleaseCommand, handoff_from_decision

logger = logging.getLogger("foragerr.search_ops.cache")

#: Server-side cache lifetime for an interactive-search result set.
CACHE_TTL_MINUTES = 30


async def cache_decisions(
    db,
    issue_id: int | None,
    decisions: list[Decision],
    *,
    ttl_minutes: int = CACHE_TTL_MINUTES,
    now: dt.datetime | None = None,
) -> None:
    """Cache each decided release keyed ``(indexer_id, guid)`` (FRG-SRCH-014).

    Upserts every row: a repeat search for the same issue refreshes the payload
    and pushes the expiry forward rather than duplicating.
    """
    now = now or utcnow()
    expires_at = now + dt.timedelta(minutes=ttl_minutes)
    rows = []
    for decision in decisions:
        handoff = handoff_from_decision(decision)
        rows.append(
            {
                "indexer_id": handoff.indexer_id,
                "guid": handoff.guid,
                "issue_id": issue_id,
                "payload": json.dumps(handoff.model_dump()),
                "created_at": now,
                "expires_at": expires_at,
            }
        )
    if not rows:
        return
    # One batched upsert keyed on the (indexer_id, guid) unique constraint: a
    # repeat search for the same release refreshes the payload and pushes the
    # expiry forward rather than duplicating — no per-row SELECT round-trip.
    stmt = sqlite_insert(ReleaseCacheRow).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[ReleaseCacheRow.indexer_id, ReleaseCacheRow.guid],
        set_={
            "issue_id": stmt.excluded.issue_id,
            "payload": stmt.excluded.payload,
            "created_at": stmt.excluded.created_at,
            "expires_at": stmt.excluded.expires_at,
        },
    )
    async with db.write_session() as session:
        await session.execute(stmt)


async def get_cached(
    db, indexer_id: int, guid: str, *, now: dt.datetime | None = None
) -> GrabReleaseCommand | None:
    """Return the cached grab hand-off for a live entry, or ``None``.

    ``None`` covers both a cache miss and an expired entry — the caller maps
    either to the same deterministic 404-class "search again" error, and never
    re-runs the search (FRG-SRCH-014 / FRG-API-008).
    """
    now = now or utcnow()
    async with db.read_session() as session:
        row = (
            await session.execute(
                select(ReleaseCacheRow).where(
                    ReleaseCacheRow.indexer_id == indexer_id,
                    ReleaseCacheRow.guid == guid,
                )
            )
        ).scalar_one_or_none()
    if row is None or row.expires_at <= now:
        return None
    # The stored payload is a GrabReleaseCommand ``model_dump`` — it round-trips
    # including the redundant ``name`` key, which the model simply re-validates.
    return GrabReleaseCommand(**json.loads(row.payload))


async def prune_expired(db, *, now: dt.datetime | None = None) -> int:
    """Delete expired ``release_cache`` rows; return how many (housekeeping)."""
    now = now or utcnow()
    async with db.write_session() as session:
        result = await session.execute(
            delete(ReleaseCacheRow).where(ReleaseCacheRow.expires_at <= now)
        )
    deleted = result.rowcount or 0
    if deleted:
        logger.info("release cache: pruned %d expired row(s)", deleted)
    return deleted


@register_command
class PruneReleaseCacheCommand(BaseCommand):
    """Scheduled prune of expired interactive-search cache rows (FRG-SRCH-014)."""

    name: Literal["prune-release-cache"] = "prune-release-cache"
    exclusivity_group: ClassVar[str | None] = "prune-release-cache"


@register_handler("prune-release-cache")
async def _handle_prune_release_cache(
    command: PruneReleaseCacheCommand, ctx: HandlerContext
) -> str:
    pruned = await prune_expired(ctx.db)
    return f"pruned {pruned} expired release_cache row(s)"
