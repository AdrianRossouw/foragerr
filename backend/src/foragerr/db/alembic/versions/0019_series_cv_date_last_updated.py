"""series.cv_date_last_updated (cv-budget-caching FRG-META-017)

Revision ID: 0019_series_cv_date_last_updated
Revises: 0018_creator_bibliography
Create Date: 2026-07-12

One additive nullable TEXT column: ``series.cv_date_last_updated`` stores, per
series, the ``date_last_updated`` value ComicVine served on the volume detail of
the last COMPLETE issue walk (FRG-META-017). It is stored VERBATIM (as CV serves
it) and compared by EQUALITY only — never parsed, never timezone-converted. A
series refresh fetches the volume detail first and, when the freshly fetched
``date_last_updated`` equals this stored value AND the last complete walk is
within the configured staleness bound, skips the issue pagination walk entirely
(ComicVine's own caching recommendation applied where our traffic repeats).

The invariant the reader relies on: **a non-NULL stamp implies the last walk was
complete.** The refresh stores the stamp ONLY after a complete walk and clears it
(to NULL) on a partial walk, so a bare equality check is sufficient — no separate
"walk complete" boolean is needed (design decision 6).

``NULL`` = "no complete walk recorded yet" is correct for every existing row, so
no data backfill is required; the first refresh after upgrade does a full walk
and stamps the column. Deliberately no index — the value is read only for the row
already loaded by ``get_series`` on the refresh path, never queried across rows.

Like 0017/0018 the column add is a plain non-FK nullable column, so alembic's
``add_column`` works directly on SQLite (no batch table rebuild).

Forward-only: no downgrade (FRG-DB-002).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019_series_cv_date_last_updated"
down_revision = "0018_creator_bibliography"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Additive nullable TEXT column (no batch table rebuild). NULL = no complete
    # walk recorded yet, which is correct for every existing series row.
    op.add_column(
        "series",
        sa.Column("cv_date_last_updated", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    raise NotImplementedError(
        "foragerr migrations are forward-only (FRG-DB-002); "
        "restore the pre-migration backup instead"
    )
