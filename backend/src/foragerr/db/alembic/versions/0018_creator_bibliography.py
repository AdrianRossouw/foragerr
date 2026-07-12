"""creator_bibliography cache + creators.bibliography_fetched_at
(m5-creator-suggestions FRG-CRTR-005)

Revision ID: 0018_creator_bibliography
Revises: 0017_issue_credits_fetched
Create Date: 2026-07-11

Adds the external-bibliography cache (FRG-CRTR-005): a ``creator_bibliography``
table holding the volumes a creator is credited on that are NOT already in the
library, fetched by the ``creator-bibliography-fetch`` command and cached
replace-per-creator. The ``creator_id`` FK is ``ON DELETE CASCADE`` so removing a
creator drops its cached rows; ``unique(creator_id, cv_volume_id)`` lists a
volume at most once per creator; the ``creator_id`` index serves the per-creator
read. In-library exclusion is deliberately NOT stored — it is a read-time
anti-join on ``series.cv_volume_id`` (FRG-API-024), so a volume added to the
library after caching disappears from suggestions without a refetch.

A single additive nullable ``creators.bibliography_fetched_at`` DATETIME records
that the cache was last successfully fetched+replaced; ``NULL`` = never fetched
(the read side reports it as pending and enqueues a fetch). ``NULL`` is correct
for every existing creator row, so no data backfill is required.

Like 0016 the new table is a pure ``create_table`` with an inline
``ForeignKeyConstraint`` + ``UniqueConstraint`` (SQLite honours FK clauses in
``CREATE TABLE``); the column add is a plain non-FK nullable DATETIME so
``add_column`` works directly on SQLite.

Forward-only: no downgrade (FRG-DB-002).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018_creator_bibliography"
down_revision = "0017_issue_credits_fetched"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "creator_bibliography",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("creator_id", sa.Integer(), nullable=False),
        sa.Column("cv_volume_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("publisher", sa.Text(), nullable=True),
        sa.Column("start_year", sa.Integer(), nullable=True),
        sa.Column("count_of_issues", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "creator_id",
            "cv_volume_id",
            name="uq_creator_bibliography_creator_volume",
        ),
    )
    op.create_index(
        "ix_creator_bibliography_creator_id", "creator_bibliography", ["creator_id"]
    )

    # Additive nullable column (no batch table rebuild) — a plain non-FK DATETIME.
    # NULL = never fetched, which is correct for every existing creator row.
    op.add_column(
        "creators",
        sa.Column("bibliography_fetched_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    raise NotImplementedError(
        "foragerr migrations are forward-only (FRG-DB-002); "
        "restore the pre-migration backup instead"
    )
