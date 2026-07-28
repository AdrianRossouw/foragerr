"""entitlement bundle display name (m11-review-experience FRG-SRC-011)

Revision ID: 0026_entitlement_bundle_name
Revises: 0025_entitlement_matched_via
Create Date: 2026-07-28

Adds ``source_entitlements.bundle_human_name`` — the ORDER's bundle display name
(``product.human_name``), parsed from every order payload since M6 and discarded
until now (design D4).

Denormalized onto the entitlement rather than given its own table: a row already
carries its ``gamekey`` (the order), a bundle's name is immutable order
metadata, and the review screen needs it on every row to group/select by bundle
at 1,318-row scale.

NULLABLE with no default and NO data rewrite in the migration: existing rows are
backfilled by the next sync, which refreshes display details on the store-native
key exactly as it does the title/publisher/format fields (FRG-SRC-003's
safe-resync rule). A row for an order that names no bundle stays NULL forever,
which is the honest value.

Additive + forward-only (FRG-DB-002).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026_entitlement_bundle_name"
down_revision = "0025_entitlement_matched_via"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "source_entitlements",
        sa.Column("bundle_human_name", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    raise NotImplementedError(
        "foragerr migrations are forward-only (FRG-DB-002); "
        "restore the pre-migration backup instead"
    )
