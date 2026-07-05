"""command backbone tables: commands, scheduled_tasks, job_history

Revision ID: 0001_command_backbone
Revises: None
Create Date: 2026-07-04

Creates the persistence for the M1 command backbone (FRG-SCHED-001/002/006/008)
under the typed, sentinel-free schema conventions (FRG-DB-008).
Forward-only: no downgrade (FRG-DB-002).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_command_backbone"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "commands",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "workload_class", sa.Text(), nullable=False, server_default="default"
        ),
        sa.Column("exclusivity_group", sa.Text(), nullable=True),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("payload_hash", sa.Text(), nullable=False),
        sa.Column("triggered_by", sa.Text(), nullable=False, server_default="manual"),
        sa.Column("queued_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued','started','completed','failed','cancelled')",
            name="ck_commands_status",
        ),
    )
    op.create_index("ix_commands_claim", "commands", ["status", "workload_class", "priority"])
    op.create_index("ix_commands_dedup", "commands", ["name", "payload_hash", "status"])

    op.create_table(
        "scheduled_tasks",
        sa.Column("name", sa.Text(), primary_key=True),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("last_run", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "job_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "command_id",
            sa.Integer(),
            sa.ForeignKey("commands.id", name="fk_job_history_command_id_commands"),
            nullable=True,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("triggered_by", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index("ix_job_history_finished", "job_history", ["finished_at"])


def downgrade() -> None:
    raise NotImplementedError(
        "foragerr migrations are forward-only (FRG-DB-002); "
        "restore the pre-migration backup instead"
    )
