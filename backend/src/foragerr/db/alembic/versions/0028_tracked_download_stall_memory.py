"""tracked-download import-visibility stall memory (m11 FRG-DL-015)

Revision ID: 0028_tracked_download_stall_memory
Revises: 0027_entitlement_proposal_attempt
Create Date: 2026-07-28

Adds two columns to ``tracked_downloads`` (design D5):

``import_stall_count``
    How many CONSECUTIVE import attempts have found no importable files under
    this download's completed output path. This kind of stall is a designed
    retry loop — the client keeps reporting the item as completed, tracking
    re-queues it as ``import_pending``, the drain blocks it again — and the
    row's instantaneous state therefore says nothing about how long the loop
    has been running. This counter is the memory that loop never had. NOT NULL
    with a server default of 0 so every pre-0028 row reads as "no stalls
    recorded", which is the honest starting point: the counter measures
    consecutive outcomes observed since the column existed.

``first_stalled_at``
    When the CURRENT stall streak began — stamped once at the first no-files
    outcome and left alone while the streak continues, so health can name the
    oldest stall rather than the most recent retry. NULLABLE: not stalling is
    the normal case and must not be asserted as a time.

Both are cleared together by any outcome that is not the no-importable-files
shape (a successful import, a per-file rejection, a corrupt archive) — real
evidence that the path is visible. Nothing else writes them; in particular the
tracking reconcile's ``import_blocked -> import_pending`` re-queue deliberately
leaves them untouched, which is the whole point of the memory.

Additive, no data rewrite, and inert to older code (which simply never reads
either column). Forward-only (FRG-DB-002).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0028_tracked_download_stall_memory"
down_revision = "0027_entitlement_proposal_attempt"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tracked_downloads",
        sa.Column(
            "import_stall_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "tracked_downloads",
        sa.Column("first_stalled_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    raise NotImplementedError(
        "foragerr migrations are forward-only (FRG-DB-002); "
        "restore the pre-migration backup instead"
    )
