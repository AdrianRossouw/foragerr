"""entitlement md5 duplicate pointer + md5 index (review-experience-2 FRG-SRC-015)

Revision ID: 0032_entitlement_duplicate_of
Revises: 0031_root_folder_read_only
Create Date: 2026-07-30

Adds one nullable column and one index to ``source_entitlements``:

``duplicate_of``
    The id of the canonical row this one is a byte-identical copy of, set only
    on a row parked at ``review_status = "duplicate"`` (FRG-SRC-015). It is an
    id reference WITHOUT a foreign key: the pointer is review bookkeeping, not
    an ownership edge — a canonical row and its copies always live in the same
    source, which already cascades as a whole, and a dangling pointer must read
    as "no set" rather than block a delete. NULL on every other row.

``ix_source_entitlements_source_md5``
    ``(source_id, md5)``. Linking asks "which rows of THIS source carry THIS
    md5", and md5 previously had no index at all — the column existed only for
    post-download integrity, which reads it off the row it already holds.

No data rewrite: every pre-0032 row reads as unlinked. The one-time startup
backfill (``foragerr.sources.dedupe``) parks pre-existing all-``new`` sets, so
the linking is done by application code that can apply the review-state rule
rather than by SQL that cannot.

Additive + forward-only (FRG-DB-002).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0032_entitlement_duplicate_of"
down_revision = "0031_root_folder_read_only"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "source_entitlements",
        sa.Column("duplicate_of", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_source_entitlements_source_md5",
        "source_entitlements",
        ["source_id", "md5"],
    )


def downgrade() -> None:
    raise NotImplementedError(
        "foragerr migrations are forward-only (FRG-DB-002); "
        "restore the pre-migration backup instead"
    )
