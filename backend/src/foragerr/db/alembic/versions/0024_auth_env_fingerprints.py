"""principal env re-seed fingerprints (m8-keys-opds FRG-AUTH-002/005)

Revision ID: 0024_auth_env_fingerprints
Revises: 0023_auth_principal_sessions
Create Date: 2026-07-12

Adds two nullable fingerprint columns to ``principal`` so the env bootstrap can
tell "the operator changed a credential IN THE APP" from "the operator changed
a credential IN THE ENVIRONMENT (recovery)":

``env_password_hash`` — a scrypt hash of the admin password that was last SEEDED
from ``FORAGERR_ADMIN_PASSWORD``. Re-seed fires only when the env password no
longer verifies against THIS fingerprint (or the username changed), never
against the live hash — so an in-app password change is not silently reverted by
a stale env var on the next boot (the footgun m8-auth-core carried).

``env_opds_password_hash`` — the same fingerprint for ``FORAGERR_OPDS_PASSWORD``,
decoupled from the admin fingerprint. NULL when OPDS defaulted to the admin
password at seed time (the env var was unset); a later boot that sets the OPDS
env var seeds it independently.

Both are NULLABLE: a v0.7.0 principal predates them, so on the first upgraded
boot the bootstrap falls back to comparing the env value against the LIVE hash
exactly once, then records the fingerprint. Forward-only: no downgrade
(FRG-DB-002).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024_auth_env_fingerprints"
down_revision = "0023_auth_principal_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "principal",
        sa.Column("env_password_hash", sa.Text(), nullable=True),
    )
    op.add_column(
        "principal",
        sa.Column("env_opds_password_hash", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    raise NotImplementedError(
        "foragerr migrations are forward-only (FRG-DB-002); "
        "restore the pre-migration backup instead"
    )
