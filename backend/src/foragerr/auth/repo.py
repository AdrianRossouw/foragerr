"""Read helpers for the single principal (FRG-AUTH-002/010).

The perimeter resolves credentials to a principal through these; kept tiny and
read-only. Writes (seed / re-seed) live in :mod:`foragerr.auth.bootstrap`.
"""

from __future__ import annotations

import hashlib

from sqlalchemy import select

from foragerr.auth.models import PrincipalRow


def api_key_hash(raw_key: str) -> str:
    """SHA-256 hex of a raw API key — the only form stored / compared."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


async def get_principal(db) -> PrincipalRow | None:
    """The single principal row, or ``None`` before bootstrap seeding."""
    async with db.read_session() as session:
        row = (
            await session.execute(select(PrincipalRow).order_by(PrincipalRow.id))
        ).scalars().first()
        if row is not None:
            session.expunge(row)
        return row


async def find_by_api_key(db, raw_key: str) -> PrincipalRow | None:
    """The principal whose stored API-key SHA-256 matches ``raw_key`` (else None)."""
    if not raw_key:
        return None
    digest = api_key_hash(raw_key)
    async with db.read_session() as session:
        row = (
            await session.execute(
                select(PrincipalRow).where(PrincipalRow.api_key_sha256 == digest)
            )
        ).scalar_one_or_none()
        if row is not None:
            session.expunge(row)
        return row


__all__ = ["api_key_hash", "get_principal", "find_by_api_key"]
