"""import_history.created_at index (m2-daily-surfaces gate fixes)

Revision ID: 0009_history_created_at_index
Revises: 0008_issue_file_fix_revision
Create Date: 2026-07-06

One additive index: ``ix_import_history_created_at`` on
``import_history.created_at`` — the DEFAULT sort column of the paged history
feed (``GET /api/v1/history``, FRG-API-011), which orders newest-first by
``created_at`` (with an ``id`` tiebreak). Without an index every page is an
unindexed sort over the whole event table; the other query columns
(download_id, issue_id, series_id, event_type) were already indexed by
``0006_import_history``, so this closes the one hot sort path the read surface
added.

Forward-only: no downgrade (FRG-DB-002).
"""

from __future__ import annotations

from alembic import op

revision = "0009_history_created_at_index"
down_revision = "0008_issue_file_fix_revision"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_import_history_created_at",
        "import_history",
        ["created_at"],
    )


def downgrade() -> None:
    raise NotImplementedError(
        "foragerr migrations are forward-only (FRG-DB-002); "
        "restore the pre-migration backup instead"
    )
