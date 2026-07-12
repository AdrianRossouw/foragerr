"""ORM models for the single principal + its sessions (FRG-AUTH-002/004).

``PrincipalRow`` is the ONE operator account (single-user tool, no user table
beyond one row, no roles). It stores only *hashes*: scrypt for the two
passwords (web + OPDS Basic), SHA-256 hex for the programmatic API key. No
credential is ever stored reversibly.

``SessionRow`` is a DB-backed opaque-token session: the row keeps only the
token's SHA-256 (``token_sha256``); the raw 256-bit token lives solely in the
client cookie, so a database leak discloses no usable session token. ``tier``
picks the sliding window (session / remember); ``expires_at`` is pruned on the
scheduler (FRG-AUTH-004).

Typed, sentinel-free column conventions from :mod:`foragerr.db.base`
(FRG-DB-008). Tables are created by migration 0023 — importing this module only
maps the models onto ``Base.metadata`` for ORM queries.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from foragerr.db.base import Base, StrictDateTime, StrictInteger

#: Session tiers (FRG-AUTH-004): a standard session and the opt-in remember-me.
SESSION_TIERS = ("session", "remember")


class PrincipalRow(Base):
    """The single operator account (FRG-AUTH-002)."""

    __tablename__ = "principal"

    id: Mapped[int] = mapped_column(StrictInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(Text, nullable=False)

    # Single-user tool: the schema itself forbids a second account. The
    # ``id = 1`` CHECK turns the bootstrap seed's check-then-insert into a hard
    # singleton — a second concurrent seeder (two instances on one DB) inserts
    # id=2 and fails with an IntegrityError instead of minting a second set of
    # valid credentials.
    __table_args__ = (CheckConstraint("id = 1", name="ck_principal_singleton"),)
    #: scrypt hash of the web login password (``scrypt$n$r$p$salt$hash``).
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    #: scrypt hash of the OPDS HTTP-Basic password (seeded = admin password
    #: unless FORAGERR_OPDS_PASSWORD is set; independent lifecycle lands later).
    opds_password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    #: SHA-256 hex of the 256-bit programmatic API key (the raw key is never
    #: persisted — high-entropy input needs no KDF).
    api_key_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(StrictDateTime, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(StrictDateTime, nullable=False)


class SessionRow(Base):
    """One authenticated session, addressed by the token's SHA-256 (FRG-AUTH-004)."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(StrictInteger, primary_key=True, autoincrement=True)
    #: SHA-256 hex of the opaque cookie token; the raw token is never stored.
    token_sha256: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    principal_id: Mapped[int] = mapped_column(
        StrictInteger,
        ForeignKey("principal.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: ``session`` (default 24 h) or ``remember`` (default 90 d).
    tier: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(StrictDateTime, nullable=False)
    last_seen_at: Mapped[dt.datetime] = mapped_column(StrictDateTime, nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(StrictDateTime, nullable=False)

    __table_args__ = (
        CheckConstraint("tier IN ('session', 'remember')", name="ck_sessions_tier"),
        Index("ix_sessions_expires_at", "expires_at"),
        Index("ix_sessions_principal_id", "principal_id"),
    )


__all__ = ["PrincipalRow", "SessionRow", "SESSION_TIERS"]
