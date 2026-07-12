"""owned-via-edition marker + entitlement grab-error (m6-humble-source A2)

Revision ID: 0022_edition_ownership_grab
Revises: 0021_sources_entitlements
Create Date: 2026-07-12

Two additive schema changes for worker A2's review/reconcile/download slice:

1. ``issue_files.edition_issue_id`` (FRG-SRC-007) — owned-via-edition
   provenance. Reconciliation of a matched collected edition writes one
   ``issue_files`` row per filled single, tagged with the trade ``issues.id``
   that provides it and ``size = 0`` (so the collected file's bytes are counted
   once, on its own file — the "no double-counting" guarantee). Because
   ownership is still "an ``issue_files`` row exists", ``wanted_issues()`` and
   ``series_statistics`` need NO new predicate and their FRG-SER-019 absence
   proof is unchanged.

   The old column-level ``UNIQUE(path)`` is replaced by a PARTIAL unique index
   over ordinary single files (``edition_issue_id IS NULL``) — behaviour-
   identical for every scan/import-written file — while edition rows are exempt
   so one collected-edition file may back several filled singles. A second
   partial unique index (``edition_issue_id IS NOT NULL``) dedupes a re-run:
   a single is filled by at most one edition.

2. ``source_entitlements.download_error`` (FRG-SRC-006) — the per-entitlement
   failed-download surface (the reason shown alongside ``download_state =
   'failed'``); cleared on retry.

SQLite cannot drop a column-level UNIQUE in place, so the ``issue_files``
rebuild uses Alembic's batch (copy-and-swap) mode. Additive + forward-only
(FRG-DB-002).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022_edition_ownership_grab"
down_revision = "0021_sources_entitlements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. issue_files: add edition_issue_id and move path-uniqueness to a partial
    #    index. The old table-level UNIQUE(path) is the NAMED constraint
    #    ``uq_issue_files_path`` (migration 0002); drop it in the same batch
    #    rebuild that adds the column (SQLite rebuilds the table copy-and-swap,
    #    preserving fix_revision/page_count added by 0008/0012).
    with op.batch_alter_table("issue_files") as batch:
        batch.add_column(sa.Column("edition_issue_id", sa.Integer(), nullable=True))
        batch.drop_constraint("uq_issue_files_path", type_="unique")
    op.create_index(
        "uq_issue_files_path_single",
        "issue_files",
        ["path"],
        unique=True,
        sqlite_where=sa.text("edition_issue_id IS NULL"),
    )
    op.create_index(
        "uq_issue_files_edition",
        "issue_files",
        ["issue_id", "edition_issue_id"],
        unique=True,
        sqlite_where=sa.text("edition_issue_id IS NOT NULL"),
    )

    # 2. source_entitlements: per-entitlement grab-failure reason.
    op.add_column(
        "source_entitlements",
        sa.Column("download_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    raise NotImplementedError(
        "foragerr migrations are forward-only (FRG-DB-002); "
        "restore the pre-migration backup instead"
    )
