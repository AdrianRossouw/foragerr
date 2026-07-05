"""series alternate search names / aliases (FRG-SRCH-003)

Revision ID: 0004_series_aliases
Revises: 0003_search_indexers
Create Date: 2026-07-05

Adds the user-editable per-series alternate search names ("aliases") the
decision engine's release-to-library mapping consumes (FRG-SRCH-003). Stored as
a nullable canonical-JSON array of raw user strings on the ``series`` row —
mirroring the existing ``series.add_options`` JSON-TEXT convention rather than a
child table (the list is small, user-maintained, and always read whole with its
series). ``NULL`` / absent means "no aliases". The engine matches on the
normalized fold of each entry; normalization happens at context-build time, not
here, so the raw text the user typed round-trips for editing.

User-maintained only: there is no ComicVine (or any external) alias feed
(FRG-SRCH-003 note). Forward-only: no downgrade (FRG-DB-002).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_series_aliases"
down_revision = "0003_search_indexers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("series", sa.Column("aliases", sa.Text(), nullable=True))


def downgrade() -> None:
    raise NotImplementedError(
        "foragerr migrations are forward-only (FRG-DB-002); "
        "restore the pre-migration backup instead"
    )
