"""entitlement md5 duplicate pointer + dedupe indexes (review-experience-2 FRG-SRC-015)

Revision ID: 0032_entitlement_duplicate_of
Revises: 0031_root_folder_read_only
Create Date: 2026-07-30

Adds two columns and two indexes to ``source_entitlements``:

``duplicate_of``
    The id of the canonical row this one is a byte-identical copy of, set only
    on a row parked at ``review_status = "duplicate"`` (FRG-SRC-015). It is an
    id reference WITHOUT a foreign key: the pointer is review bookkeeping, not
    an ownership edge — a canonical row and its copies always live in the same
    source, which already cascades as a whole, and a dangling pointer must read
    as "no set" rather than block a delete. NULL on every other row.

``dedupe_opt_out``
    Whether the operator restored this row out of a duplicate parking. The
    linking pass never parks a flagged row again (FRG-SRC-015), so a restore
    survives the next sync instead of being silently reversed. NOT NULL with a
    false server default: every pre-0032 row has made no such decision, and a
    nullable "maybe opted out" would need a three-way read at every link.

``ix_source_entitlements_source_md5``
    ``(source_id, md5)``. Linking reads "the md5-bearing rows of THIS source"
    and groups them in memory; md5 previously had no index at all — the column
    existed only for post-download integrity, which reads it off the row it
    already holds.

``ix_source_entitlements_duplicate_of``
    The copies chip's read is "which rows point at these canonicals"
    (``foragerr.sources.repo.duplicate_copies``), issued on every listing of a
    review queue that runs to thousands of rows; without this index that is a
    full table scan on the review screen's hot path.

No data rewrite: every pre-0032 row reads as unlinked and not opted out. The
startup backfill (``foragerr.sources.dedupe``) parks pre-existing sets, so the
linking is done by application code that can apply the review-state rule rather
than by SQL that cannot.

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
    op.add_column(
        "source_entitlements",
        sa.Column(
            "dedupe_opt_out",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        "ix_source_entitlements_source_md5",
        "source_entitlements",
        ["source_id", "md5"],
    )
    op.create_index(
        "ix_source_entitlements_duplicate_of",
        "source_entitlements",
        ["duplicate_of"],
    )


def downgrade() -> None:
    raise NotImplementedError(
        "foragerr migrations are forward-only (FRG-DB-002); "
        "restore the pre-migration backup instead"
    )
