"""entitlement proposal attempt stamp + error flag (m11-cv-budget FRG-SRC-013)

Revision ID: 0027_entitlement_proposal_attempt
Revises: 0026_entitlement_bundle_name
Create Date: 2026-07-28

Adds two nullable columns to ``source_entitlements`` (design D5):

``proposal_attempted_at``
    When a proposal-computing pass last TOUCHED this row — set whether the pass
    produced a proposal, produced the no-plausible-match marker, deferred on the
    ComicVine budget, or errored. Enrichment orders its pending set
    never-attempted-first then oldest-attempt-first, so a failing or deferred
    head can only delay its OWN retry, never the first attempt of the rows
    behind it. NULL means "never attempted", which is why it sorts first.

``proposal_attempt_error``
    Whether that last attempt errored on the ComicVine consultation. Needed as
    its OWN column because the two deferral shapes are indistinguishable from
    the row otherwise: a budget-deferred row and a CV-errored row both keep a
    NULL ``proposed_match_json`` and both carry an attempt stamp, yet only the
    errored one may be spaced out (``comicvine_error_retry_spacing_seconds``).
    Spacing a budget-deferred row would turn a transient window refusal into a
    day-long freeze. NULL = never attempted, or attempted before this column
    existed.

Both are NULLABLE with no default and NO data rewrite: every pre-0027 row reads
as never-attempted, which puts the whole existing backlog at the head of the
first post-upgrade run's ordering — the honest starting state, and the one that
converges fastest.

Neither column gates eligibility. FRG-SRC-010 stands unchanged: a budget hit
still leaves the row's ``proposed_match_json`` NULL and the row retryable; the
stamps change ORDER only.

Additive + forward-only (FRG-DB-002).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0027_entitlement_proposal_attempt"
down_revision = "0026_entitlement_bundle_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "source_entitlements",
        sa.Column("proposal_attempted_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "source_entitlements",
        sa.Column("proposal_attempt_error", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    raise NotImplementedError(
        "foragerr migrations are forward-only (FRG-DB-002); "
        "restore the pre-migration backup instead"
    )
