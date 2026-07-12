"""principal + sessions tables (m8-auth-core FRG-AUTH-002/004)

Revision ID: 0023_auth_principal_sessions
Revises: 0022_edition_ownership_grab
Create Date: 2026-07-12

Creates the two tables the default-deny auth perimeter needs:

``principal`` — the SINGLE operator account (single-user tool, no roles). Holds
the scrypt ``password_hash`` (web login), the scrypt ``opds_password_hash``
(HTTP Basic realm on /opds), and ``api_key_sha256`` (the programmatic API key
stored only as its SHA-256 hex — the high-entropy raw key needs no KDF and is
never persisted in plaintext). The row is seeded at first authed boot by
``foragerr.auth.bootstrap`` from ``FORAGERR_ADMIN_USER`` /
``FORAGERR_ADMIN_PASSWORD`` — NOT here — because hashing needs the env
credentials the Alembic context does not carry. This migration only provisions
the empty tables.

``sessions`` — DB-backed opaque-token sessions (FRG-AUTH-004). Only the token's
SHA-256 is stored (``token_sha256``, UNIQUE); the raw 256-bit token lives only
in the client cookie. ``tier`` is ``session`` (default 24 h) or ``remember``
(default 90 d), both sliding; ``expires_at`` is pruned on the scheduler.

Forward-only: no downgrade (FRG-DB-002).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023_auth_principal_sessions"
down_revision = "0022_edition_ownership_grab"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "principal",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("opds_password_hash", sa.Text(), nullable=False),
        sa.Column("api_key_sha256", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        # Single-user tool: enforce ONE account at the schema level. A second
        # concurrent bootstrap seeder (two instances sharing an empty DB) gets
        # id=2 and fails this CHECK rather than minting a second valid API key.
        sa.CheckConstraint("id = 1", name="ck_principal_singleton"),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("token_sha256", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "principal_id",
            sa.Integer(),
            sa.ForeignKey("principal.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tier", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "tier IN ('session', 'remember')", name="ck_sessions_tier"
        ),
    )
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])
    op.create_index("ix_sessions_principal_id", "sessions", ["principal_id"])


def downgrade() -> None:
    raise NotImplementedError(
        "foragerr migrations are forward-only (FRG-DB-002); "
        "restore the pre-migration backup instead"
    )
