"""first-run seed marker: app_state table + established-install pre-set

Revision ID: 0010_first_run_marker
Revises: 0009_history_created_at_index
Create Date: 2026-07-06

Adds the small ``app_state`` key/value meta table that holds the first-run DDL
seed marker (FRG-DEP-013). The actual provider seeding runs as a startup
provisioning step (``foragerr.db.first_run``) AFTER ``import foragerr.ddl`` has
populated the getcomics/ddl registry — it cannot run inside a migration because
the registry is only populated at import time.

To protect an ESTABLISHED installation (one that already carries user config)
from having providers injected on upgrade, this migration pre-sets the marker
as already-seeded for any database that already has an ``indexers`` /
``download_clients`` / ``series`` row. A genuinely fresh (empty) database gets
no marker here, so the startup step seeds it exactly once.

Forward-only: no downgrade (FRG-DB-002).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

from foragerr.db.first_run import APP_STATE_TABLE, SEED_MARKER_KEY, SEED_MARKER_VALUE

revision = "0010_first_run_marker"
down_revision = "0009_history_created_at_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        APP_STATE_TABLE,
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
    )

    # FRG-DEP-013: pre-set the first-run marker on an ESTABLISHED database so an
    # upgrade never gets DDL providers injected. "Established" = already carries
    # user configuration: any pre-existing indexers / download_clients / series
    # row. A fresh (empty) DB matches none of these, so no marker is written and
    # the startup step seeds it on first run.
    op.get_bind().execute(
        text(
            f"INSERT INTO {APP_STATE_TABLE} (key, value) "
            "SELECT :key, :value WHERE "
            "EXISTS (SELECT 1 FROM indexers) OR "
            "EXISTS (SELECT 1 FROM download_clients) OR "
            "EXISTS (SELECT 1 FROM series)"
        ),
        {"key": SEED_MARKER_KEY, "value": SEED_MARKER_VALUE},
    )


def downgrade() -> None:
    raise NotImplementedError(
        "foragerr migrations are forward-only (FRG-DB-002); "
        "restore the pre-migration backup instead"
    )
