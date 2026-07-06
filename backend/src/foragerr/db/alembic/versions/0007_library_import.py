"""library-import staging groups (m2-existing-library-import)

Revision ID: 0007_library_import
Revises: 0006_import_history
Create Date: 2026-07-06

One additive table (design decision 2): ``library_import_groups`` persists the
root-folder scan's staging — files of one would-be series grouped by the
parser's shared ``matching_key`` normalization, with the per-group ComicVine
match proposal, the user's confirmation/override/skip decision, and the import
outcome — so the review survives a restart (FRG-IMP-023) and a big library scan
is never redone per page load. A re-scan replaces a root's rows atomically, so
no housekeeping is needed for stale groups; deleting a root folder cascades its
staging away.

Forward-only: no downgrade (FRG-DB-002).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_library_import"
down_revision = "0006_import_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "library_import_groups",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        # The shared normalized series key the group's files parsed to (or the
        # folder-name fallback for an unparseable group).
        sa.Column("matching_key", sa.Text(), nullable=False),
        sa.Column(
            "root_folder_id",
            sa.Integer(),
            sa.ForeignKey(
                "root_folders.id",
                name="fk_library_import_groups_root_folder_id_root_folders",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        # The group's on-disk folder (series path_override for in-place import).
        sa.Column("folder", sa.Text(), nullable=False),
        # Canonical-JSON array of {"path", "size"} objects.
        sa.Column("files", sa.Text(), nullable=False),
        # Mean parse confidence over the group's files (0.0-1.0).
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("proposed_cv_volume_id", sa.Integer(), nullable=True),
        sa.Column("confirmed_cv_volume_id", sa.Integer(), nullable=True),
        # state ∈ proposed | confirmed | no_match | imported | skipped.
        sa.Column("state", sa.Text(), nullable=False, server_default="proposed"),
        # Human-visible outcome/annotation (no-match reason, blocked reasons).
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("scanned_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "root_folder_id", "matching_key", name="uq_library_import_root_key"
        ),
        sa.CheckConstraint(
            "state IN ('proposed','confirmed','no_match','imported','skipped')",
            name="library_import_state_valid",
        ),
    )
    op.create_index(
        "ix_library_import_groups_root_folder_id",
        "library_import_groups",
        ["root_folder_id"],
    )


def downgrade() -> None:
    raise NotImplementedError(
        "foragerr migrations are forward-only (FRG-DB-002); "
        "restore the pre-migration backup instead"
    )
