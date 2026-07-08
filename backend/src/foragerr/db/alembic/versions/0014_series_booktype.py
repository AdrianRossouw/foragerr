"""series collected-edition (trade) book-type typing (m3-trade-typing FRG-SER-018)

Revision ID: 0014_series_booktype
Revises: 0013_series_groups
Create Date: 2026-07-08

Adds *display/naming-only* collected-edition typing to the series model
(FRG-SER-018): two additive columns on ``series`` — a nullable ``booktype``
(a lowercased/underscored parser ``Booktype`` value ``tpb``/``gn``/``hc``/
``one_shot``; NULL = an ordinary single-issues run) and a defaulted
``booktype_locked`` flag (the operator-override lock, so a later refresh does
not re-derive over the operator's choice).

Typing never alters series identity, matching, monitoring, or wanted state —
no book-type predicate ever reaches ``wanted_issues()``/``series_statistics``,
and trades are a separate CV volume -> separate series (FRG-SER-019). No
``wanted`` column, no CHECK-constraint change (the schema-hygiene guard stays
green). Both columns are additive (nullable / server-defaulted) so existing
rows need no backfill: a series is typed lazily on its next add/refresh
derivation and stays NULL (single-issues) until then.

Forward-only: no downgrade (FRG-DB-002).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014_series_booktype"
down_revision = "0013_series_groups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Additive column adds (nullable / server-defaulted) — no batch table
    # rebuild. ``booktype`` defaults to NULL (single-issues run); a plain
    # non-FK TEXT column, so alembic's ``add_column`` works directly on SQLite.
    op.add_column(
        "series",
        sa.Column("booktype", sa.Text(), nullable=True),
    )
    op.add_column(
        "series",
        sa.Column(
            "booktype_locked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    raise NotImplementedError(
        "foragerr migrations are forward-only (FRG-DB-002); "
        "restore the pre-migration backup instead"
    )
