"""pull-entry display enrichment (m11 FRG-PULL-011)

Revision ID: 0029_pull_entry_enrichment
Revises: 0028_tracked_download_stall_memory
Create Date: 2026-07-29

Adds five columns to ``pull_entries`` (design D4) for the payload fields the
ingest previously dropped on the floor:

``cover_url``
    The entry's primary cover, canonicalized (query and fragment stripped) and
    stored ONLY when it satisfied the cover allowlist at ingest — anything
    relative, non-HTTPS, off-host, off-prefix, or traversal-bearing stores as
    NULL (fail-closed). Query-stripping is what makes a re-fetch idempotent:
    the source appends a cache-buster that changes between fetches.

``description``, ``upc``
    Sanitized, length-bounded source text.

``creators``, ``characters``
    Compact JSON arrays of ``{"role", "name"}`` / ``{"name"}``, count-capped at
    ingest. The source's own creator/character ids are dropped — nothing links
    to them.

All five are NULLABLE: absent enrichment is the normal case for an older stored
week (they populate on that week's next refresh — no backfill) and for any
entry whose source data was missing or refused. None of them is status-shaped:
the D4 invariant — a pull entry carries a link and a match discriminator, never
a wanted/downloaded/skipped state of its own — is untouched.

Additive, no data rewrite, and inert to older code (which simply never reads
any of them). Forward-only (FRG-DB-002).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0029_pull_entry_enrichment"
down_revision = "0028_tracked_download_stall_memory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in ("cover_url", "description", "upc", "creators", "characters"):
        op.add_column("pull_entries", sa.Column(column, sa.Text(), nullable=True))


def downgrade() -> None:
    raise NotImplementedError(
        "foragerr migrations are forward-only (FRG-DB-002); "
        "restore the pre-migration backup instead"
    )
