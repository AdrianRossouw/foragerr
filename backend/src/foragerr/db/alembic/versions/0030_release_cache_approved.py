"""release_cache grab approval gate (m11 FRG-API-008)

Revision ID: 0030_release_cache_approved
Revises: 0029_pull_entry_enrichment
Create Date: 2026-07-29

Adds a single nullable ``approved`` boolean to ``release_cache`` (design D1): the
decision's approved verdict recorded beside its grab hand-off, so ``POST
/release`` can enforce the quality gate without re-searching.

Fail-safe by construction: the column is NULLABLE with no server default, so a
row written by pre-0030 code (or any row where the verdict was not recorded)
reads as NULL and is treated as NOT approved — the grab is refused and offered a
force override, never silently grabbed.

Additive, no data rewrite, inert to older code (which never reads it).
Forward-only (FRG-DB-002).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0030_release_cache_approved"
down_revision = "0029_pull_entry_enrichment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "release_cache", sa.Column("approved", sa.Boolean(), nullable=True)
    )


def downgrade() -> None:
    raise NotImplementedError(
        "foragerr migrations are forward-only (FRG-DB-002); "
        "restore the pre-migration backup instead"
    )
