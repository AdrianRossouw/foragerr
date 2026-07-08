"""series_groups franchise grouping (m3-volume-grouping FRG-SER-016/017)

Revision ID: 0013_series_groups
Revises: 0012_issue_file_page_count
Create Date: 2026-07-08

Adds the *display-only* franchise-grouping layer over the one-series-per-CV-
volume model (FRG-SER-016): a new ``series_groups`` table (a franchise header
with a display ``title`` and its normalized ``grouping_key``) and two additive
columns on ``series`` — a nullable ``series_group_id`` FK (``ON DELETE SET
NULL`` so removing a group never touches its members) and a defaulted
``group_locked`` flag (the operator-override lock, FRG-SER-017).

Grouping never alters series identity, matching, monitoring, or wanted state —
no ``wanted`` column, no CHECK-constraint change (the schema-hygiene guard
stays green). The two series columns are additive (nullable / server-defaulted)
so existing rows need no backfill; a series is auto-grouped lazily on its next
add/refresh derivation and stays ungrouped (``NULL``) until then.

Forward-only: no downgrade (FRG-DB-002).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_series_groups"
down_revision = "0012_issue_file_page_count"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "series_groups",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("grouping_key", sa.Text(), nullable=False),
        sa.Column(
            "manual_title", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("grouping_key", name="uq_series_groups_grouping_key"),
    )

    # Additive column adds (nullable / server-defaulted) — no batch table
    # rebuild. The FK column rides a RAW ``ALTER TABLE ... ADD COLUMN`` with an
    # inline ``REFERENCES`` clause: SQLite supports that directly (the column
    # is nullable, defaulting to NULL, as SQLite requires for an added FK
    # column), whereas alembic's ``add_column(ForeignKey(...))`` routes through
    # the unsupported "ALTER constraint" path on the SQLite dialect. Enforced
    # only when ``PRAGMA foreign_keys=ON``; ``ON DELETE SET NULL`` keeps a
    # group deletion from ever cascading to its member series.
    op.execute(
        "ALTER TABLE series ADD COLUMN series_group_id INTEGER "
        "REFERENCES series_groups (id) ON DELETE SET NULL"
    )
    op.add_column(
        "series",
        sa.Column(
            "group_locked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index("ix_series_series_group_id", "series", ["series_group_id"])


def downgrade() -> None:
    raise NotImplementedError(
        "foragerr migrations are forward-only (FRG-DB-002); "
        "restore the pre-migration backup instead"
    )
