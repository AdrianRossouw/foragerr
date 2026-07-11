"""ORM models for the creators domain (FRG-CRTR-002/004).

Uses the typed/sentinel-free column conventions from :mod:`foragerr.db.base`
(FRG-DB-008). Two tables:

- :class:`CreatorRow` — one person, keyed by the unique ComicVine person id.
  ComicVine is the authority for ``name`` (refresh updates it); the user owns
  only ``followed``, and a follow is only ever explicit (FRG-CRTR-004, owner
  decision 2026-07-11 — reconciliation never derives one). ``follow_touched``
  records that the user has explicitly toggled the flag; pruning a
  user-unfollowed creator would erase that memory, so the prune step spares any
  touched row (and any followed row).
- :class:`IssueCreditRow` — the per-issue credit association (issue FK CASCADE
  -> creator FK CASCADE), carrying the normalized role (constrained to
  :data:`foragerr.metadata.credits.ROLE_VOCABULARY`) plus the verbatim role
  token. Unique on ``(issue_id, creator_id, role_normalized)`` so a creator is
  credited at most once per role per issue.

The tables themselves are created by the forward-only 0016 migration, not by
``create_all``; these models are the typed read/write surface over them.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from foragerr.db.base import Base, StrictDateTime, StrictInteger

# ``issue_id`` below is a cross-package FK (string-resolved at mapper-
# configuration time) to ``library.models.IssueRow``'s ``issues`` table. Import
# the module — not just the name — so that table is registered on the shared
# ``Base.metadata`` before anything triggers SQLAlchemy's mapper configuration,
# regardless of which module happens to import ``foragerr.creators.models``
# first (mirrors ``foragerr.pull.models``' cross-package FK handling).
import foragerr.library.models  # noqa: F401
from foragerr.metadata.credits import ROLE_VOCABULARY


class CreatorRow(Base):
    """One creator (person), keyed by the ComicVine person id (FRG-CRTR-002)."""

    __tablename__ = "creators"

    id: Mapped[int] = mapped_column(StrictInteger, primary_key=True, autoincrement=True)
    cv_person_id: Mapped[int] = mapped_column(StrictInteger, nullable=False, unique=True)
    #: CV-authoritative display name — already sanitized at ingest
    #: (:func:`foragerr.metadata.sanitize.sanitize_cv_text`). Plain ``Text`` (not
    #: ``SentinelFreeText``): the value is deterministic post-sanitization, is
    #: ``NOT NULL``, and a legitimately sentinel-shaped name (a person named
    #: "None") must not fold to SQL NULL and trip the constraint — same
    #: reasoning as ``series.matching_key``.
    name: Mapped[str] = mapped_column(Text, nullable=False)
    #: User-owned follow flag (FRG-CRTR-004). Only ever set by the explicit follow
    #: API — the system never seeds, defaults, or derives it from library contents
    #: (owner decision 2026-07-11).
    followed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Set (to "now") the first time the USER toggles ``followed`` via the API.
    #: ``NULL`` = never user-touched; prune spares any non-NULL row even when
    #: creditless, so a deliberate unfollow is never resurrected.
    follow_touched: Mapped[dt.datetime | None] = mapped_column(
        StrictDateTime, nullable=True
    )
    #: When ``followed`` last became true (via an explicit user follow);
    #: display-only.
    followed_at: Mapped[dt.datetime | None] = mapped_column(StrictDateTime, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(StrictDateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("cv_person_id", name="uq_creators_cv_person_id"),
    )


class IssueCreditRow(Base):
    """One per-issue person credit (FRG-CRTR-002).

    Both FKs cascade on delete: removing an issue (or a creator) drops the
    dependent credit rows and nothing else. Deleting an issue therefore cascades
    its credits at the DB level (``PRAGMA foreign_keys=ON``); a creator left with
    zero credits is then pruned by reconciliation unless the user has touched it.
    """

    __tablename__ = "issue_credits"

    id: Mapped[int] = mapped_column(StrictInteger, primary_key=True, autoincrement=True)
    issue_id: Mapped[int] = mapped_column(
        StrictInteger, ForeignKey("issues.id", ondelete="CASCADE"), nullable=False
    )
    creator_id: Mapped[int] = mapped_column(
        StrictInteger, ForeignKey("creators.id", ondelete="CASCADE"), nullable=False
    )
    #: Normalized role from the fixed vocabulary — internally derived enum value,
    #: plain ``Text`` guarded by the CHECK constraint below.
    role_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    #: The verbatim (sanitized) CV role token retained for display/refinement.
    #: Plain ``Text``: preserving it verbatim is the point, so no sentinel fold.
    role_verbatim: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint(
            f"role_normalized IN {ROLE_VOCABULARY!r}",
            name="issue_credits_role_normalized_valid",
        ),
        UniqueConstraint(
            "issue_id",
            "creator_id",
            "role_normalized",
            name="uq_issue_credits_issue_creator_role",
        ),
        Index("ix_issue_credits_issue_id", "issue_id"),
        Index("ix_issue_credits_creator_id", "creator_id"),
    )
