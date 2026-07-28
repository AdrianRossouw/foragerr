"""entitlement match provenance (m11-source-import-trust FRG-PP-022)

Revision ID: 0025_entitlement_matched_via
Revises: 0024_auth_env_fingerprints
Create Date: 2026-07-28

Adds ``source_entitlements.matched_via`` — HOW the entitlement's
``matched_series_id`` was established:

``operator`` — a human action (the review screen's match/add, the add's
FRG-SRC-008 degrade-to-match, a bulk match).
``auto``     — auto-sync accepted a proposal above the confidence threshold
               (``sources.enrich._auto_accept``); no human chose this series.

The discriminator exists for one safety decision (FRG-PP-022 guard 3): the
ordinal fallback ("Vol. N" → issue N under a known series) is only safe because
a human chose the series, so it fires for ``operator`` matches only.

NULLABLE, and NULL is treated as NOT operator-made. ``_auto_accept`` shipped
with the original sources change (9b763d8, M6) — long before this column — so a
pre-upgrade ``matched_series_id`` on a source with ``auto_sync`` on is
indistinguishable from an operator match. Rather than grant the fallback to
matches we cannot prove a human made, legacy rows keep the pre-change behaviour
(a bare "Vol. N" file blocks for manual import); a single re-match through the
review UI stamps ``operator`` and restores it.

Additive + forward-only (FRG-DB-002).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025_entitlement_matched_via"
down_revision = "0024_auth_env_fingerprints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "source_entitlements",
        sa.Column("matched_via", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    raise NotImplementedError(
        "foragerr migrations are forward-only (FRG-DB-002); "
        "restore the pre-migration backup instead"
    )
