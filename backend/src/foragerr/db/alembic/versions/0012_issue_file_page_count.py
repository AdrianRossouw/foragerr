"""issue_files.page_count (m3-opds-page-streaming OPDS-PSE)

Revision ID: 0012_issue_file_page_count
Revises: 0011_pull_entries
Create Date: 2026-07-08

One additive nullable column: ``issue_files.page_count`` caches the archive's
image-page count for OPDS Page-Streaming ``pse:count`` (FRG-OPDS-009). It is
populated at import from ``ArchiveReport.image_count`` for a listable archive
(no extra archive open) and left ``NULL`` otherwise. ``NULL`` = not yet computed
(legacy/scan-discovered row) or an unlistable archive; the OPDS path computes it
lazily on first access from the freshly-listed members and writes it back, and a
stored-size mismatch against the on-disk file forces a recompute — so existing
rows need no backfill.

Forward-only: no downgrade (FRG-DB-002).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_issue_file_page_count"
down_revision = "0011_pull_entries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "issue_files",
        # NULL = not yet computed (legacy/scan row) or an unlistable archive; the
        # OPDS lazy path computes and writes it back on first access.
        sa.Column("page_count", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    raise NotImplementedError(
        "foragerr migrations are forward-only (FRG-DB-002); "
        "restore the pre-migration backup instead"
    )
