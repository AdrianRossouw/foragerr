"""pull_entries: weekly-pull idempotent storage (m3-pull-backbone, area A)

Revision ID: 0011_pull_entries
Revises: 0010_first_run_marker
Create Date: 2026-07-06

One additive table (FRG-PULL-003): ``pull_entries`` stores the weekly-pull
projection's raw source rows, keyed ``(week, entry_key)`` unique so a re-fetch
of the same week can replace-on-refresh idempotently (``foragerr.pull.repo.
replace_week``). Each row carries publisher/series_name/issue_number, the
source-supplied ComicVine ids as *candidates* only, a release date, and —
the D4 invariant — only a nullable ``matched_issue_id`` link plus a
``match_type`` discriminator (``id`` / ``name_seq`` / ``unmatched`` /
``new_series``); it has no wanted/downloaded/skipped status column of its
own. That state lives on ``issues`` / the download queue and is computed by
the metadata-derived projection (FRG-PULL-001), not stored here.

Forward-only: no downgrade (FRG-DB-002).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_pull_entries"
down_revision = "0010_first_run_marker"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pull_entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        # ISO year-week key, e.g. "2026-W27".
        sa.Column("week", sa.Text(), nullable=False),
        # Deterministic per-week identity: prefers the source cv_issue_id,
        # else a normalized (series_name, issue_number, publisher) tuple.
        sa.Column("entry_key", sa.Text(), nullable=False),
        sa.Column("publisher", sa.Text(), nullable=True),
        sa.Column("series_name", sa.Text(), nullable=False),
        # Raw source token verbatim; normalized only at match time.
        sa.Column("issue_number", sa.Text(), nullable=False),
        # Source-supplied ComicVine ids — candidates only, never authority.
        sa.Column("cv_series_id", sa.Integer(), nullable=True),
        sa.Column("cv_issue_id", sa.Integer(), nullable=True),
        sa.Column("release_date", sa.Date(), nullable=False),
        # The LINK (D4) — nullable, never a status. SET NULL on issue delete
        # so a historical pull entry survives, unlinked, rather than
        # disappearing with the issue it once pointed at.
        sa.Column(
            "matched_issue_id",
            sa.Integer(),
            sa.ForeignKey(
                "issues.id",
                name="fk_pull_entries_matched_issue_id_issues",
                ondelete="SET NULL",
            ),
            nullable=True,
        ),
        # match_type ∈ id | name_seq | unmatched | new_series.
        sa.Column("match_type", sa.Text(), nullable=False, server_default="unmatched"),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("week", "entry_key", name="uq_pull_entries_week_entry_key"),
        sa.CheckConstraint(
            "match_type IN ('id','name_seq','unmatched','new_series')",
            name="pull_match_type_valid",
        ),
    )
    op.create_index("ix_pull_entries_week", "pull_entries", ["week"])
    op.create_index(
        "ix_pull_entries_matched_issue_id", "pull_entries", ["matched_issue_id"]
    )


def downgrade() -> None:
    raise NotImplementedError(
        "foragerr migrations are forward-only (FRG-DB-002); "
        "restore the pre-migration backup instead"
    )
