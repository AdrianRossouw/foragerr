"""issues.credits_fetched_at (m5-credits-live-fetch FRG-CRTR-002)

Revision ID: 0017_issue_credits_fetched
Revises: 0016_creators_credits
Create Date: 2026-07-11

One additive nullable column: ``issues.credits_fetched_at`` records that a
series refresh successfully fetched this issue's per-issue person credits from
the ComicVine issue detail endpoint (``issue/4050-{id}/``) — the ONLY endpoint
that serves ``person_credits`` (the list endpoint returns null, verified live
2026-07-11). A stamped issue is "credits covered" and is never re-fetched; an
unstamped (``NULL``) issue is "credit-needing" and the refresh fetch phase picks
it up, newest-first, up to the ``credits_fetch_per_refresh`` bound. A successful
fetch stamps the column even when the issue legitimately has zero credits, so a
golden-age library never re-fetches the same creditless issues forever
(FRG-CRTR-001/002).

``NULL`` = needs fetch is exactly right for every existing row, so no data
backfill is required. Deliberately no index: target selection reads a series'
STAMPED rows (``series_id = ? AND credits_fetched_at IS NOT NULL``, served by
``ix_issues_series_id``) and diffs against the just-walked records so brand-new
issues are eligible the same run — a partial ``IS NULL`` index could not serve
that read (gate finding).

Forward-only: no downgrade (FRG-DB-002).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017_issue_credits_fetched"
down_revision = "0016_creators_credits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Additive nullable column (no batch table rebuild) — a plain non-FK
    # DATETIME, so alembic's ``add_column`` works directly on SQLite.
    op.add_column(
        "issues",
        sa.Column("credits_fetched_at", sa.DateTime(), nullable=True),
    )
    # Deliberately NO index on the column: the refresh fetch phase reads the
    # STAMPED rows for one series (``WHERE series_id = ? AND credits_fetched_at
    # IS NOT NULL``) and diffs against the just-walked issue records — brand-new
    # issues become fetch-eligible in the same run, which an ``IS NULL`` query
    # over stored rows would miss. That per-series read is served by the
    # existing ``ix_issues_series_id``; a partial ``IS NULL`` index cannot
    # serve it and would be dead weight (gate finding, m5-credits-live-fetch).


def downgrade() -> None:
    raise NotImplementedError(
        "foragerr migrations are forward-only (FRG-DB-002); "
        "restore the pre-migration backup instead"
    )
