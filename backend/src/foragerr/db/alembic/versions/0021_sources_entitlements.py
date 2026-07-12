"""sources + source_entitlements tables (m6-humble-source FRG-SRC-001)

Revision ID: 0021_sources_entitlements
Revises: 0020_keystore_meta
Create Date: 2026-07-12

Creates the two store-source tables (design decision 1):

``sources`` — one row per connected store account: its ``type`` (``humble``),
the encrypted-at-rest ``settings`` JSON (the ``_simpleauth_sess`` cookie born
encrypted via the keystore, exactly like an indexer's api_key), a
``connection_state`` (``connected`` / ``expired`` / ``disconnected``), the
per-source ``auto_sync`` toggle (ships OFF, owner 2026-07-11), and last-sync
metadata.

``source_entitlements`` — one row per owned store item (subproduct), keyed by
the store-native identity ``(source_id, gamekey, machine_name)`` so a re-sync
is a stable idempotent diff (FRG-SRC-003). Carries the display fields, a
content ``classification`` (``comic`` / ``other``) and a review ``review_status``
(``new`` / ``matched`` / ``ignored``) on SEPARATE axes from the ``download_state``
(design decision 2), the API-provided per-format ``md5`` / ``file_size`` /
``filename`` for the preferred grabbable copy plus the full ``formats_json``
list, and the proposed/actual match columns (populated by later workers — NULL
until then; the signed download URL is NEVER stored, it is re-fetched fresh at
grab time per design decision 8).

Additive only; the feature is invisible until a source is connected.
Forward-only: no downgrade (FRG-DB-002).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021_sources_entitlements"
down_revision = "0020_keystore_meta"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("settings", sa.Text(), nullable=False),
        sa.Column(
            "connection_state",
            sa.Text(),
            nullable=False,
            server_default="disconnected",
        ),
        sa.Column(
            "auto_sync", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("last_sync_at", sa.DateTime(), nullable=True),
        sa.Column("last_sync_status", sa.Text(), nullable=True),
        sa.Column("added_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_sources_type", "sources", ["type"])

    op.create_table(
        "source_entitlements",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Store-native diff identity (design decision 1): gamekey + subproduct
        # machine_name, unique per source.
        sa.Column("gamekey", sa.Text(), nullable=False),
        sa.Column("machine_name", sa.Text(), nullable=False),
        sa.Column("human_name", sa.Text(), nullable=False),
        sa.Column("publisher", sa.Text(), nullable=True),
        # Content classification axis: 'comic' | 'other' (FRG-SRC-003).
        sa.Column("classification", sa.Text(), nullable=False),
        # Review-status axis: 'new' | 'matched' | 'ignored' (design decision 2).
        sa.Column(
            "review_status", sa.Text(), nullable=False, server_default="new"
        ),
        # Download/import-progress axis, SEPARATE from review status (design
        # decision 2): NULL until a later worker queues a grab.
        sa.Column("download_state", sa.Text(), nullable=True),
        # Preferred grabbable copy's API-provided metadata (the signed URL is
        # NEVER stored — re-fetched fresh at grab time, design decision 8).
        sa.Column("preferred_format", sa.Text(), nullable=True),
        sa.Column("md5", sa.Text(), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("filename", sa.Text(), nullable=True),
        # Every available download option for this item as JSON
        # [{"name","md5","file_size","platform"}], so a later worker can grab a
        # non-preferred format without a re-classification.
        sa.Column(
            "formats_json", sa.Text(), nullable=False, server_default="[]"
        ),
        # Proposed-match seam (worker A2 computes the ranking; NULL until then).
        sa.Column("proposed_series_id", sa.Integer(), nullable=True),
        sa.Column("proposed_match_json", sa.Text(), nullable=True),
        # Operator-chosen match target (review workflow; NULL until matched).
        sa.Column("matched_series_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "source_id",
            "gamekey",
            "machine_name",
            name="uq_source_entitlements_native_key",
        ),
    )
    op.create_index(
        "ix_source_entitlements_source_review",
        "source_entitlements",
        ["source_id", "review_status"],
    )
    op.create_index(
        "ix_source_entitlements_source_classification",
        "source_entitlements",
        ["source_id", "classification"],
    )


def downgrade() -> None:
    raise NotImplementedError(
        "foragerr migrations are forward-only (FRG-DB-002); "
        "restore the pre-migration backup instead"
    )
