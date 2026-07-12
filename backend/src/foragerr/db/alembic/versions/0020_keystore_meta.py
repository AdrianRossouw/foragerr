"""keystore_meta single-row table (m6-keystore FRG-AUTH-008)

Revision ID: 0020_keystore_meta
Revises: 0019_series_cv_date_last_updated
Create Date: 2026-07-12

Creates the single-row ``keystore_meta`` table holding the non-secret keystore
material: a random per-deployment ``salt`` (BLOB) and an encrypted ``sentinel``
check-value (the fixed sentinel plaintext encrypted under the derived key,
stored as its urlsafe-base64 Fernet token), plus a ``created_at`` stamp. The
row (id=1) is written at first keyed boot by ``foragerr.keystore.init_keystore``
— NOT here — because deriving the key needs the ``FORAGERR_SECRET_KEY``
passphrase, which the Alembic offline/startup context does not carry. This
migration only provisions the empty table.

The passphrase itself is never persisted (environment-only). Losing it costs
re-entry of stored secrets, never data (FRG-AUTH-012).

Forward-only: no downgrade (FRG-DB-002).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020_keystore_meta"
down_revision = "0019_series_cv_date_last_updated"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "keystore_meta",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("salt", sa.LargeBinary(), nullable=False),
        sa.Column("sentinel", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    raise NotImplementedError(
        "foragerr migrations are forward-only (FRG-DB-002); "
        "restore the pre-migration backup instead"
    )
