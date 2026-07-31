"""entitlement classification provenance (mark-non-comic FRG-SRC-016)

Revision ID: 0033_entitlement_classified_via
Revises: 0032_entitlement_duplicate_of
Create Date: 2026-07-31

Adds one column to ``source_entitlements``:

``classified_via``
    WHO settled this row's ``classification`` — ``operator`` when a human marked
    it non-comic (or back to comic), NULL when the automatic classifier owns it.
    It follows the ``matched_via`` provenance pattern rather than a boolean lock
    so a later automatic-provenance value stays possible without a second
    column. Nullable because NULL is the honest reading of every pre-0033 row
    and of every row the operator has never touched: nobody stated anything, so
    the sync write-back keeps re-deriving the classification (FRG-SRC-012). Only
    the operator value is load-bearing, and it is never cleared automatically —
    the reverse mark is another operator mark, not a return to automatic.

No data rewrite and no server default: an added NULL column already says
"classified automatically" for every existing row, which is exactly what was
true before the column existed.

Additive + forward-only (FRG-DB-002).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0033_entitlement_classified_via"
down_revision = "0032_entitlement_duplicate_of"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "source_entitlements",
        sa.Column("classified_via", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    raise NotImplementedError(
        "foragerr migrations are forward-only (FRG-DB-002); "
        "restore the pre-migration backup instead"
    )
