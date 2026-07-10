"""trade containment side table (m4-series-detail FRG-SER-020)

Revision ID: 0015_issue_collections
Revises: 0014_series_booktype
Create Date: 2026-07-10

Adds the *display-only* trade-containment layer (FRG-SER-020): a dedicated
``issue_collections`` side table mapping one issue of a trade-typed series
(one collected book) to a target series plus a contiguous issue range,
expressed as copied ordering-key bounds. One row per contiguous sub-range, so
a non-contiguous collection (``#1–#6`` + ``#8``) or a multi-series omnibus is
several rows. Each row carries a human-readable ``range_label`` and a
``source``/``confidence`` provenance (v1 writes only ``declared``; the columns
exist so a later description-derived-suggestion feature lands without a
migration).

Containment lives ENTIRELY here — no column on ``series`` or ``issues`` — and
is display-only: the derived-wanted choke point (``repo.wanted_issues``) and
``series_statistics`` never reference this table, extending the FRG-SER-019
never-suppress invariant (proven by the compiled-SQL absence test). Both
foreign keys are ``ON DELETE CASCADE`` so deleting the trade issue or the
target series removes the dependent containment rows and nothing else.

Unlike 0013's series-group FK columns (which needed a raw ``ALTER TABLE`` to
add an FK column to an existing SQLite table), this is a pure new table, so
``create_table`` with inline ``ForeignKeyConstraint``s works directly — SQLite
supports FK clauses in ``CREATE TABLE``, only not in ``ALTER``.

Forward-only: no downgrade (FRG-DB-002).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015_issue_collections"
down_revision = "0014_series_booktype"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "issue_collections",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("trade_issue_id", sa.Integer(), nullable=False),
        sa.Column("target_series_id", sa.Integer(), nullable=False),
        sa.Column("start_ordering_key", sa.Text(), nullable=False),
        sa.Column("end_ordering_key", sa.Text(), nullable=False),
        sa.Column("range_label", sa.Text(), nullable=False),
        sa.Column(
            "source", sa.Text(), nullable=False, server_default="declared"
        ),
        sa.Column(
            "confidence", sa.Float(), nullable=False, server_default=sa.text("1.0")
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["trade_issue_id"], ["issues.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["target_series_id"], ["series.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "source IN ('declared', 'derived_description')",
            name="issue_collections_source_valid",
        ),
    )
    op.create_index(
        "ix_issue_collections_trade_issue_id",
        "issue_collections",
        ["trade_issue_id"],
    )
    op.create_index(
        "ix_issue_collections_target_series",
        "issue_collections",
        ["target_series_id", "start_ordering_key", "end_ordering_key"],
    )


def downgrade() -> None:
    raise NotImplementedError(
        "foragerr migrations are forward-only (FRG-DB-002); "
        "restore the pre-migration backup instead"
    )
