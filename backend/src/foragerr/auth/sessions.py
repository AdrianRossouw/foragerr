"""DB-backed opaque-token sessions, two sliding tiers (FRG-AUTH-004).

A session token is 256 bits of ``secrets`` randomness delivered in the
``foragerr_session`` cookie; the database stores only its SHA-256
(:func:`token_hash`), so a leaked ``sessions`` table yields no usable token.

Two tiers share the table, distinguished by ``tier``: ``session`` (default 24 h)
and ``remember`` (default 90 d), both *sliding* — authenticated use pushes
``expires_at`` forward from now. Writes on the sliding path are throttled to at
most once per :data:`TOUCH_THROTTLE_SECONDS` per session so a burst of requests
does not write the row on every call.

- :func:`create_session` mints a fresh token every login (fixation defense — a
  pre-existing cookie never survives a new login).
- :func:`authenticate` resolves a raw token to its principal, rejecting expired
  rows and sliding a live one forward.
- :func:`logout` deletes one row; :func:`invalidate_all` deletes every row on
  a credential re-seed; :func:`invalidate_others` deletes every row EXCEPT the
  acting one on an in-app password change (the operator keeps their session).
- :func:`prune_expired` is the scheduler's housekeeping delete.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import secrets
from dataclasses import dataclass

from sqlalchemy import delete, select

from foragerr.auth.models import SessionRow
from foragerr.db.base import utcnow

logger = logging.getLogger("foragerr.auth")

COOKIE_NAME = "foragerr_session"

#: 32 bytes = 256 bits of token entropy (FRG-AUTH-004).
TOKEN_BYTES = 32

#: Minimum seconds between two sliding ``last_seen``/``expires_at`` writes for
#: one session — bounds write amplification under a request burst.
TOUCH_THROTTLE_SECONDS = 60


def new_token() -> str:
    """A fresh opaque 256-bit URL-safe session token (raw — cookie only)."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def token_hash(token: str) -> str:
    """SHA-256 hex of a raw token — the only form ever stored server-side."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tier_seconds(tier: str, settings) -> int:
    """The configured sliding window (seconds) for ``tier``."""
    if tier == "remember":
        return settings.remember_timeout_seconds
    return settings.session_timeout_seconds


@dataclass(frozen=True)
class AuthedSession:
    """The outcome of a successful token authentication."""

    principal_id: int
    tier: str
    token: str


async def create_session(
    db,
    principal_id: int,
    *,
    tier: str,
    settings,
    now: dt.datetime | None = None,
) -> str:
    """Create a session row and return the RAW token (store only its hash).

    Called on every login, so the returned token is always fresh — any cookie
    the client already held is not reused (session-fixation defense)."""
    now = now or utcnow()
    token = new_token()
    expires = now + dt.timedelta(seconds=tier_seconds(tier, settings))
    async with db.write_session() as session:
        session.add(
            SessionRow(
                token_sha256=token_hash(token),
                principal_id=principal_id,
                tier=tier,
                created_at=now,
                last_seen_at=now,
                expires_at=expires,
            )
        )
    return token


async def authenticate(
    db, token: str, *, settings, now: dt.datetime | None = None
) -> AuthedSession | None:
    """Resolve a raw token to its live session, sliding expiry forward.

    Returns ``None`` for an unknown, or expired, token (an expired row is left
    for the prune job, never treated as valid). On success the row's
    ``last_seen``/``expires_at`` slide forward from ``now`` — throttled to one
    write per :data:`TOUCH_THROTTLE_SECONDS` so hot paths do not write per call.
    """
    if not token:
        return None
    now = now or utcnow()
    digest = token_hash(token)
    async with db.read_session() as session:
        row = (
            await session.execute(
                select(SessionRow).where(SessionRow.token_sha256 == digest)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        if row.expires_at <= now:
            return None
        principal_id = row.principal_id
        tier = row.tier
        last_seen = row.last_seen_at
    # Slide the window, throttled: only write when the last touch is old enough.
    if (now - last_seen).total_seconds() >= TOUCH_THROTTLE_SECONDS:
        new_expiry = now + dt.timedelta(seconds=tier_seconds(tier, settings))
        async with db.write_session() as session:
            fresh = (
                await session.execute(
                    select(SessionRow).where(SessionRow.token_sha256 == digest)
                )
            ).scalar_one_or_none()
            # Re-check under the writer: a concurrent logout may have deleted it.
            if fresh is not None and fresh.expires_at > now:
                fresh.last_seen_at = now
                fresh.expires_at = new_expiry
    return AuthedSession(principal_id=principal_id, tier=tier, token=token)


async def logout(db, token: str) -> bool:
    """Delete the session row for ``token``; return whether a row was removed."""
    if not token:
        return False
    async with db.write_session() as session:
        result = await session.execute(
            delete(SessionRow).where(SessionRow.token_sha256 == token_hash(token))
        )
    return bool(result.rowcount)


async def invalidate_all(db, principal_id: int) -> int:
    """Delete every session for a principal (bootstrap re-seed / password reset)."""
    async with db.write_session() as session:
        result = await session.execute(
            delete(SessionRow).where(SessionRow.principal_id == principal_id)
        )
    return result.rowcount or 0


async def invalidate_others(db, principal_id: int, acting_token: str) -> int:
    """Delete every session for a principal EXCEPT the acting one (FRG-AUTH-004).

    The credential-lifecycle counterpart to :func:`invalidate_all`: an in-app web
    password change revokes every OTHER session (a second device, a lingering
    remember-me cookie) while the operator who made the change keeps their
    current session — no self-logout on a routine rotation. The acting session is
    named by its RAW token (from ``request.state.session_token``); only its
    SHA-256 is compared, never stored anew. An empty/absent ``acting_token``
    (e.g. an API-key-authed caller with no session to preserve) degrades to
    "delete all". Returns the number of rows deleted."""
    keep = token_hash(acting_token) if acting_token else None
    async with db.write_session() as session:
        stmt = delete(SessionRow).where(SessionRow.principal_id == principal_id)
        if keep is not None:
            stmt = stmt.where(SessionRow.token_sha256 != keep)
        result = await session.execute(stmt)
    return result.rowcount or 0



async def prune_expired(db, *, now: dt.datetime | None = None) -> int:
    """Delete expired session rows (scheduler housekeeping, FRG-AUTH-004)."""
    now = now or utcnow()
    async with db.write_session() as session:
        result = await session.execute(
            delete(SessionRow).where(SessionRow.expires_at <= now)
        )
    deleted = result.rowcount or 0
    if deleted:
        logger.info("auth: pruned %d expired session row(s)", deleted)
    return deleted


__all__ = [
    "COOKIE_NAME",
    "TOKEN_BYTES",
    "TOUCH_THROTTLE_SECONDS",
    "AuthedSession",
    "authenticate",
    "create_session",
    "invalidate_all",
    "invalidate_others",
    "logout",
    "new_token",
    "prune_expired",
    "tier_seconds",
    "token_hash",
]
