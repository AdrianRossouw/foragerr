"""search + indexer tables: indexers, provider_backoff, release_cache

Revision ID: 0003_search_indexers
Revises: 0002_library_metadata
Create Date: 2026-07-05

Creates the persistence for the M1 search/indexer domain under the typed,
sentinel-free schema conventions (FRG-DB-008). A SINGLE forward migration
(design decision 10) creates all three tables:

- ``indexers`` — the provider-pattern configuration rows (FRG-IDX-001/002/004).
- ``provider_backoff`` — the generic per-provider back-off ladder state, keyed
  ``(provider_type, provider_id)`` so download clients / DDL reuse it in change
  5 without a schema change (FRG-IDX-010, FRG-NFR-005).
- ``release_cache`` — the interactive-search grab cache keyed indexer_id+guid
  with an expiry (FRG-SRCH-014 / FRG-API-008); consumed by the search area.

Forward-only: no downgrade (FRG-DB-002).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_search_indexers"
down_revision = "0002_library_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "indexers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("implementation", sa.Text(), nullable=False),
        sa.Column("protocol", sa.Text(), nullable=False, server_default="usenet"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="25"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("enable_rss", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("enable_auto", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "enable_interactive",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("settings", sa.Text(), nullable=False),
        sa.Column("retention_override", sa.Integer(), nullable=True),
        sa.Column("caps_fetched_at", sa.DateTime(), nullable=True),
        sa.Column("caps_json", sa.Text(), nullable=True),
        sa.Column(
            "caps_degraded", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("added_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_indexers_enabled", "indexers", ["enabled"])

    op.create_table(
        "provider_backoff",
        sa.Column("provider_type", sa.Text(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_allowed_at", sa.DateTime(), nullable=True),
        sa.Column("last_reason", sa.Text(), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint(
            "provider_type", "provider_id", name="pk_provider_backoff"
        ),
    )

    op.create_table(
        "release_cache",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "indexer_id",
            sa.Integer(),
            sa.ForeignKey(
                "indexers.id",
                name="fk_release_cache_indexer_id_indexers",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("guid", sa.Text(), nullable=False),
        sa.Column("issue_id", sa.Integer(), nullable=True),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "indexer_id", "guid", name="uq_release_cache_indexer_guid"
        ),
    )
    op.create_index("ix_release_cache_expires_at", "release_cache", ["expires_at"])
    op.create_index("ix_release_cache_issue_id", "release_cache", ["issue_id"])


def downgrade() -> None:
    raise NotImplementedError(
        "foragerr migrations are forward-only (FRG-DB-002); "
        "restore the pre-migration backup instead"
    )
