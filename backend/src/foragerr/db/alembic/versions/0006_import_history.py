"""import history + quarantine bookkeeping (change 6, m1-import-pipeline)

Revision ID: 0006_import_history
Revises: 0005_download_clients
Create Date: 2026-07-05

A SINGLE forward migration (design Migration Plan) laying the change-6 schema
that the pipeline / renamer / flows areas build on WITHOUT a second migration.
Only the schema lands here; the behavior that writes and reads it is Wave B.

- ``import_history`` — one row per pipeline outcome (FRG-PP-011): grabbed,
  imported, import_failed, import_blocked, download_failed, file_deleted,
  file_renamed, upgrade_replaced. Keyed for join by the download-client
  ``download_id`` (nullable — rescan-sourced events have no download), carrying
  the series/issue, source title, event provenance, a per-event JSON ``data``
  payload (reasons, per-field evidence provenance), and — for upgrade-replaced
  events — the ``quarantine_path`` the superseded file was moved to. This is the
  M1 quarantine bookkeeping stand-in for the M2 recycle bin (design decision 8):
  the replaced file is moved to ``<config>/quarantine/<date>/`` (never deleted)
  and its destination recorded on the history event, so M2 can adopt FRG-PP-013
  without a schema change.

Remote-path mappings (FRG-PP-008) reuse the ``remote_path_mappings`` table
already created in change 5 (migration 0005) — no new table here. The
import-blocked condition is represented by the existing
``tracked_downloads.state`` text enum value plus its ``status_messages`` reason
payload; no new column is needed for it.

Forward-only: no downgrade (FRG-DB-002).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_import_history"
down_revision = "0005_download_clients"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- import_history: one row per pipeline outcome (FRG-PP-011) ------------
    op.create_table(
        "import_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        # download-client join key; nullable for rescan-sourced events.
        sa.Column("download_id", sa.Text(), nullable=True),
        sa.Column("series_id", sa.Integer(), nullable=True),
        sa.Column("issue_id", sa.Integer(), nullable=True),
        # event_type ∈ grabbed | imported | import_failed | import_blocked |
        # download_failed | file_deleted | file_renamed | upgrade_replaced.
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("source_title", sa.Text(), nullable=True),
        # provenance of the event source: 'download' | 'rescan' (extensible).
        sa.Column("source", sa.Text(), nullable=True),
        # per-event JSON payload: reasons, per-field evidence provenance, etc.
        sa.Column("data", sa.Text(), nullable=True),
        # upgrade-replaced only: where the superseded file was quarantined
        # (M1 stand-in for the M2 recycle bin, design decision 8).
        sa.Column("quarantine_path", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_import_history_download_id", "import_history", ["download_id"])
    op.create_index("ix_import_history_issue_id", "import_history", ["issue_id"])
    op.create_index("ix_import_history_series_id", "import_history", ["series_id"])
    op.create_index("ix_import_history_event_type", "import_history", ["event_type"])


def downgrade() -> None:
    raise NotImplementedError(
        "foragerr migrations are forward-only (FRG-DB-002); "
        "restore the pre-migration backup instead"
    )
