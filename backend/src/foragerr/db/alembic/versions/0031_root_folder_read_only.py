"""read-only library roots (read-only-library FRG-SER-021)

Revision ID: 0031_root_folder_read_only
Revises: 0030_release_cache_approved
Create Date: 2026-07-29

Adds one additive, defaulted ``read_only`` boolean to ``root_folders``
(FRG-SER-021): a root so flagged is a read-only reference library — indexed
in place, served over OPDS, never written to (no rename/move/download/delete)
and its series never monitored/searched/acquired. Existing roots default to
``false`` (writable, unchanged behaviour), so no backfill is needed. A plain
non-FK Boolean, so alembic's ``add_column`` works directly on SQLite with no
batch rebuild (mirrors 0014's ``booktype_locked``).

Forward-only: no downgrade (FRG-DB-002).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0031_root_folder_read_only"
down_revision = "0030_release_cache_approved"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "root_folders",
        sa.Column(
            "read_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    raise NotImplementedError(
        "foragerr migrations are forward-only (FRG-DB-002); "
        "restore the pre-migration backup instead"
    )
