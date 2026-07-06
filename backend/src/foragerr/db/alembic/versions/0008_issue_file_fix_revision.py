"""issue_files.fix_revision (m2-existing-library-import gate fixes)

Revision ID: 0008_issue_file_fix_revision
Revises: 0007_library_import
Create Date: 2026-07-06

One additive nullable column: ``issue_files.fix_revision`` persists the
imported file's `(fN)` fixed-release marker revision (FRG-PP-014). Renaming
strips the marker from the placed basename, so without a persisted value a
marker-bearing winner became invisible to future duplicate contests — a later
larger unfixed challenger would beat the fixed release it must never beat. The
duplicate evaluation reads this column first and falls back to parsing the
stored basename for legacy rows, so existing rows need no backfill (NULL =
unfixed or legacy).

Forward-only: no downgrade (FRG-DB-002).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_issue_file_fix_revision"
down_revision = "0007_library_import"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "issue_files",
        # NULL = unfixed, or a legacy row predating the column (read side then
        # falls back to the stored-basename parse).
        sa.Column("fix_revision", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    raise NotImplementedError(
        "foragerr migrations are forward-only (FRG-DB-002); "
        "restore the pre-migration backup instead"
    )
