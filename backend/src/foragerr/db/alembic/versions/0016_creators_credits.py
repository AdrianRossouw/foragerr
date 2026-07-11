"""creators + per-issue credits (m5-creators-backbone FRG-CRTR-002)

Revision ID: 0016_creators_credits
Revises: 0015_issue_collections
Create Date: 2026-07-11

Adds the creators backbone (FRG-CRTR-002): a ``creators`` table (one person,
keyed by the unique ComicVine person id, with the user-owned ``followed`` flag,
its ``followed_at`` timestamp, and the ``follow_touched`` user-ownership marker
that lets reconciliation seeding tell "never touched" from "deliberately
unfollowed" — FRG-CRTR-004), and an ``issue_credits`` association mapping one
issue to one creator in one normalized role. Both FKs are ``ON DELETE CASCADE``
so deleting the issue or the creator drops the dependent credit rows and nothing
else; the ``role_normalized`` CHECK is built from :data:`_FROZEN_ROLE_VOCABULARY`
below — a frozen snapshot of the role vocabulary as of this migration, NOT the
live ``foragerr.metadata.credits.ROLE_VOCABULARY`` — and the
``(issue_id, creator_id, role_normalized)`` unique constraint makes credit
reconciliation a clean per-key diff.

Like 0015 these are pure new tables, so ``create_table`` with inline
``ForeignKeyConstraint``s / ``CheckConstraint`` / ``UniqueConstraint`` works
directly (SQLite honours FK clauses in ``CREATE TABLE``, only not in ``ALTER``).

The one-time credits-backfill trigger (FRG-CRTR-003, next worker) reuses the
EXISTING ``app_state`` key/value meta table (added by 0010) rather than a new
marker table — a single ``creators_backfill_done`` row is all it needs — so no
marker table is created here.

Forward-only: no downgrade (FRG-DB-002).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016_creators_credits"
down_revision = "0015_issue_collections"
branch_labels = None
depends_on = None

#: FROZEN copy of the normalized-role vocabulary AS OF THIS MIGRATION
#: (2026-07-11). Historical migrations must be immutable: the schema an already-
#: applied migration produced can never change, so this literal tuple MUST NOT be
#: rewired to import the live ``foragerr.metadata.credits.ROLE_VOCABULARY``. If it
#: tracked that constant, a future vocabulary edit would make a *fresh* install
#: (running 0016 today) and an *upgraded* install (that ran 0016 before the edit)
#: build divergent CHECK constraints from the same revision. When the vocabulary
#: legitimately changes, ship a NEW migration that ALTERs the constraint — do not
#: touch this tuple. ``tests/creators/test_migration_role_vocabulary`` asserts
#: this equals the CURRENT live vocabulary and fails the day they diverge,
#: pointing the future developer at that new-migration path.
_FROZEN_ROLE_VOCABULARY = (
    "writer",
    "artist",
    "penciler",
    "inker",
    "colorist",
    "letterer",
    "cover",
    "editor",
    "other",
)


def upgrade() -> None:
    op.create_table(
        "creators",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("cv_person_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "followed", sa.Boolean(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("follow_touched", sa.DateTime(), nullable=True),
        sa.Column("followed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("cv_person_id", name="uq_creators_cv_person_id"),
    )

    roles = ", ".join(repr(role) for role in _FROZEN_ROLE_VOCABULARY)
    op.create_table(
        "issue_credits",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("issue_id", sa.Integer(), nullable=False),
        sa.Column("creator_id", sa.Integer(), nullable=False),
        sa.Column("role_normalized", sa.Text(), nullable=False),
        sa.Column("role_verbatim", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["issue_id"], ["issues.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            f"role_normalized IN ({roles})",
            name="issue_credits_role_normalized_valid",
        ),
        sa.UniqueConstraint(
            "issue_id",
            "creator_id",
            "role_normalized",
            name="uq_issue_credits_issue_creator_role",
        ),
    )
    op.create_index("ix_issue_credits_issue_id", "issue_credits", ["issue_id"])
    op.create_index("ix_issue_credits_creator_id", "issue_credits", ["creator_id"])


def downgrade() -> None:
    raise NotImplementedError(
        "foragerr migrations are forward-only (FRG-DB-002); "
        "restore the pre-migration backup instead"
    )
