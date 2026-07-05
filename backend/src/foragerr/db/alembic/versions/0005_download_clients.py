"""download client + tracking + DDL tables (change 5, m1-downloads)

Revision ID: 0005_download_clients
Revises: 0004_series_aliases
Create Date: 2026-07-05

A SINGLE forward migration (design decision, Migration Plan) creating ALL SIX
change-5 tables under the typed, sentinel-free schema conventions (FRG-DB-008),
so the three change-5 worktree areas (downloads / tracking / ddl) build on one
schema without a second migration:

- ``download_clients`` — the download-client provider-pattern configuration
  rows, mirroring ``indexers`` (FRG-DL-001/002): implementation + JSON settings,
  enable flag, priority, remove-completed-downloads flag.
- ``grab_history`` — one Grabbed row per issue at grab time, keyed by the client
  download id join key (FRG-DL-006). Written by the tracking area.
- ``tracked_downloads`` — the per-download tracking state machine row
  (FRG-DL-007): ``state`` holds the canonical
  :class:`foragerr.downloads.state.TrackedDownloadState` text enum. Driven by
  the tracking area.
- ``blocklist`` — multi-field failed-release rows (FRG-DL-012). Written by the
  tracking area's failure loop.
- ``remote_path_mappings`` — per-client remote→local prefix rewrites applied to
  completed output paths (FRG-DL-005). Read by the downloads area.
- ``ddl_queue`` — the built-in DDL client's persistent, single-flight download
  queue (FRG-DDL-007). Driven by the ddl area.

The ``download_clients``/``grab_history``/``blocklist``/``ddl_queue`` schemas
are designed here from the dl + ddl specs and design decisions so the tracking
and ddl areas fill in behavior without editing this migration.

Forward-only: no downgrade (FRG-DB-002).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_download_clients"
down_revision = "0004_series_aliases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- download_clients: provider-pattern config rows (FRG-DL-001/002) ------
    op.create_table(
        "download_clients",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("implementation", sa.Text(), nullable=False),
        sa.Column("protocol", sa.Text(), nullable=False, server_default="usenet"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="25"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "remove_completed_downloads",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("settings", sa.Text(), nullable=False),
        sa.Column("added_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_download_clients_enabled", "download_clients", ["enabled"])

    # --- grab_history: one Grabbed row per issue, download_id join key --------
    op.create_table(
        "grab_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("download_id", sa.Text(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=True),
        sa.Column("series_id", sa.Integer(), nullable=True),
        sa.Column("issue_id", sa.Integer(), nullable=True),
        sa.Column("indexer_id", sa.Integer(), nullable=True),
        sa.Column("indexer_name", sa.Text(), nullable=True),
        sa.Column("guid", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("link", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("pub_date", sa.DateTime(), nullable=True),
        sa.Column("protocol", sa.Text(), nullable=False, server_default="usenet"),
        # provenance: 'indexer' | 'ddl' (FRG-DL-006 / FRG-DDL-001).
        sa.Column("source", sa.Text(), nullable=False, server_default="indexer"),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_grab_history_download_id", "grab_history", ["download_id"])
    op.create_index("ix_grab_history_issue_id", "grab_history", ["issue_id"])

    # --- tracked_downloads: the per-download state machine (FRG-DL-007) -------
    op.create_table(
        "tracked_downloads",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("download_id", sa.Text(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=True),
        sa.Column("client_name", sa.Text(), nullable=True),
        sa.Column("protocol", sa.Text(), nullable=False, server_default="usenet"),
        sa.Column("source", sa.Text(), nullable=False, server_default="indexer"),
        # state ∈ TrackedDownloadState (text); status ∈ ok|warning|error.
        sa.Column("state", sa.Text(), nullable=False, server_default="downloading"),
        sa.Column("status", sa.Text(), nullable=False, server_default="ok"),
        sa.Column("status_messages", sa.Text(), nullable=True),
        sa.Column("series_id", sa.Integer(), nullable=True),
        sa.Column("issue_id", sa.Integer(), nullable=True),
        sa.Column("indexer_name", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("total_size", sa.Integer(), nullable=True),
        sa.Column("remaining_size", sa.Integer(), nullable=True),
        sa.Column("estimated_time", sa.Integer(), nullable=True),
        sa.Column("output_path", sa.Text(), nullable=True),
        sa.Column("encrypted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("added_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "client_id", "download_id", name="uq_tracked_downloads_client_download"
        ),
    )
    op.create_index("ix_tracked_downloads_state", "tracked_downloads", ["state"])
    op.create_index(
        "ix_tracked_downloads_download_id", "tracked_downloads", ["download_id"]
    )

    # --- blocklist: multi-field failed-release rows (FRG-DL-012) --------------
    op.create_table(
        "blocklist",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("series_id", sa.Integer(), nullable=True),
        sa.Column("issue_id", sa.Integer(), nullable=True),
        sa.Column("source_title", sa.Text(), nullable=True),
        sa.Column("guid", sa.Text(), nullable=True),
        sa.Column("indexer_id", sa.Integer(), nullable=True),
        sa.Column("indexer_name", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("publish_date", sa.DateTime(), nullable=True),
        sa.Column("protocol", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        # DDL matches by source URL/title rather than guid+indexer (FRG-DL-012).
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("download_id", sa.Text(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_blocklist_issue_id", "blocklist", ["issue_id"])
    op.create_index("ix_blocklist_series_id", "blocklist", ["series_id"])

    # --- remote_path_mappings: per-client remote→local rewrites (FRG-DL-005) --
    op.create_table(
        "remote_path_mappings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "client_id",
            sa.Integer(),
            sa.ForeignKey(
                "download_clients.id",
                name="fk_remote_path_mappings_client_id_download_clients",
                ondelete="CASCADE",
            ),
            nullable=True,
        ),
        sa.Column("host", sa.Text(), nullable=False),
        sa.Column("remote_path", sa.Text(), nullable=False),
        sa.Column("local_path", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_remote_path_mappings_client_id", "remote_path_mappings", ["client_id"]
    )

    # --- ddl_queue: the built-in DDL client's persistent queue (FRG-DDL-007) --
    op.create_table(
        "ddl_queue",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("download_id", sa.Text(), nullable=False),
        # status ∈ queued|downloading|completed|failed|paused|aborted.
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("series_id", sa.Integer(), nullable=True),
        sa.Column("issue_id", sa.Integer(), nullable=True),
        sa.Column("provider_id", sa.Integer(), nullable=True),
        sa.Column("post_url", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("expected_size", sa.Integer(), nullable=True),
        sa.Column("bytes_received", sa.Integer(), nullable=False, server_default="0"),
        # ordered candidate link list + failover bookkeeping (FRG-DDL-004/005).
        sa.Column("links_json", sa.Text(), nullable=True),
        sa.Column("current_host", sa.Text(), nullable=True),
        sa.Column("current_link", sa.Text(), nullable=True),
        sa.Column("selected_link_type", sa.Text(), nullable=True),
        sa.Column("failed_hosts_json", sa.Text(), nullable=True),
        sa.Column("staging_path", sa.Text(), nullable=True),
        sa.Column("output_path", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("download_id", name="uq_ddl_queue_download_id"),
    )
    op.create_index("ix_ddl_queue_status", "ddl_queue", ["status"])


def downgrade() -> None:
    raise NotImplementedError(
        "foragerr migrations are forward-only (FRG-DB-002); "
        "restore the pre-migration backup instead"
    )
