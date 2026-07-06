"""library domain tables: root_folders, series, issues, issue_files,
format_profiles

Revision ID: 0002_library_metadata
Revises: 0001_command_backbone
Create Date: 2026-07-05

Creates the persistence for the M1 library domain (FRG-SER-001/002/003/004/
008/009, FRG-QUAL-001/002) under the typed, sentinel-free schema conventions
(FRG-DB-008), plus the idempotent default-format-profile data seed
(FRG-QUAL-002). Forward-only: no downgrade (FRG-DB-002).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from foragerr.quality.models import seed_default_format_profile

revision = "0002_library_metadata"
down_revision = "0001_command_backbone"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "format_profiles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("formats", sa.Text(), nullable=False),
        sa.Column("cutoff", sa.Text(), nullable=False),
        sa.UniqueConstraint("name", name="uq_format_profiles_name"),
    )

    op.create_table(
        "root_folders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("path", sa.Text(), nullable=False),
        sa.UniqueConstraint("path", name="uq_root_folders_path"),
    )

    op.create_table(
        "series",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("cv_volume_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("sort_title", sa.Text(), nullable=False),
        sa.Column("matching_key", sa.Text(), nullable=False),
        sa.Column("publisher", sa.Text(), nullable=True),
        sa.Column("start_year", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="continuing"),
        sa.Column("monitored", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "monitor_new_items", sa.Text(), nullable=False, server_default="all"
        ),
        sa.Column(
            "format_profile_id",
            sa.Integer(),
            sa.ForeignKey(
                "format_profiles.id", name="fk_series_format_profile_id_format_profiles"
            ),
            nullable=False,
        ),
        sa.Column(
            "root_folder_id",
            sa.Integer(),
            sa.ForeignKey("root_folders.id", name="fk_series_root_folder_id_root_folders"),
            nullable=False,
        ),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("cover_cached_at", sa.DateTime(), nullable=True),
        sa.Column("added_at", sa.DateTime(), nullable=False),
        sa.Column("refreshed_at", sa.DateTime(), nullable=True),
        sa.Column("description_sanitized", sa.Text(), nullable=True),
        sa.Column("add_options", sa.Text(), nullable=True),
        sa.UniqueConstraint("cv_volume_id", name="uq_series_cv_volume_id"),
        sa.UniqueConstraint("path", name="uq_series_path"),
        sa.CheckConstraint(
            "status IN ('continuing','ended')", name="ck_series_status_valid"
        ),
        sa.CheckConstraint(
            "monitor_new_items IN ('all','none')",
            name="ck_series_monitor_new_items_valid",
        ),
    )
    op.create_index("ix_series_matching_key", "series", ["matching_key"])
    op.create_index("ix_series_root_folder_id", "series", ["root_folder_id"])

    op.create_table(
        "issues",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "series_id",
            sa.Integer(),
            sa.ForeignKey("series.id", name="fk_issues_series_id_series", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cv_issue_id", sa.Integer(), nullable=False),
        sa.Column("issue_number", sa.Text(), nullable=True),
        sa.Column("ordering_key", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("cover_date", sa.Date(), nullable=True),
        sa.Column("store_date", sa.Date(), nullable=True),
        sa.Column("issue_type", sa.Text(), nullable=False, server_default="regular"),
        sa.Column("monitored", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("added_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("cv_issue_id", name="uq_issues_cv_issue_id"),
        sa.CheckConstraint(
            "issue_type IN ('regular','annual','special','tpb-content')",
            name="ck_issues_issue_type_valid",
        ),
    )
    op.create_index("ix_issues_series_id", "issues", ["series_id"])
    op.create_index("ix_issues_series_ordering", "issues", ["series_id", "ordering_key"])

    op.create_table(
        "issue_files",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "issue_id",
            sa.Integer(),
            sa.ForeignKey("issues.id", name="fk_issue_files_issue_id_issues", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("added_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("path", name="uq_issue_files_path"),
    )
    op.create_index("ix_issue_files_issue_id", "issue_files", ["issue_id"])

    # FRG-QUAL-002: seed exactly one default format profile, idempotently.
    seed_default_format_profile(op.get_bind())


def downgrade() -> None:
    raise NotImplementedError(
        "foragerr migrations are forward-only (FRG-DB-002); "
        "restore the pre-migration backup instead"
    )
