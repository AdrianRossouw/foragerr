"""ORM models for the indexer domain (FRG-IDX-001) and the grab cache.

``IndexerRow`` is the provider-pattern configuration row (design decision 1):
one ``indexers`` table for every implementation, settings as validated JSON,
three independent usage toggles, and the caps-probe snapshot (including the
degraded-defaults marker) persisted on the row.

``ReleaseCacheRow`` (table ``release_cache``) is created by the same migration
(design decision 10 mandates a single migration) but *consumed* by the search /
release-API area: the interactive-search grab cache keyed ``indexer_id + guid``
with an expiry (FRG-SRCH-014 / FRG-API-008). It is defined here so the one
migration has an authoritative model to mirror; this area does not read it.

Uses the typed, sentinel-free column conventions from :mod:`foragerr.db.base`
(FRG-DB-008). ``settings``/``caps_json`` are internally-generated JSON, so plain
``Text`` (mirroring ``commands.payload``), never ``SentinelFreeText``.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from foragerr.db.base import Base, StrictDateTime, StrictInteger

#: Fetch paths gated by the three independent usage toggles (FRG-IDX-002).
USAGE_PATHS = ("rss", "auto", "interactive")


class IndexerRow(Base):
    """A configured indexer (FRG-IDX-001)."""

    __tablename__ = "indexers"

    id: Mapped[int] = mapped_column(StrictInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    #: Implementation identifier (registry key), e.g. ``newznab``.
    implementation: Mapped[str] = mapped_column(Text, nullable=False)
    #: Wire protocol (``usenet`` today; ``torrent`` when Torznab lands in M2).
    protocol: Mapped[str] = mapped_column(Text, nullable=False, default="usenet")
    priority: Mapped[int] = mapped_column(StrictInteger, nullable=False, default=25)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: Three independent usage toggles (FRG-IDX-002); every fetch path selects
    #: only rows whose corresponding toggle is on.
    enable_rss: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    enable_auto: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    enable_interactive: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    #: Validated implementation settings as canonical JSON (SecretStr values
    #: stored as their raw string; the row loader re-registers them for
    #: redaction — FRG-IDX-001 scenario 3).
    settings: Mapped[str] = mapped_column(Text, nullable=False)
    #: Per-indexer usenet retention override in days (FRG-IDX-009); ``None``
    #: means "use the global retention".
    retention_override: Mapped[int | None] = mapped_column(
        StrictInteger, nullable=True
    )
    #: Caps-probe snapshot (FRG-IDX-004): when it was fetched, the resolved
    #: capabilities as JSON, and whether the probe degraded to conservative
    #: defaults (recorded on the row rather than blocking configuration).
    caps_fetched_at: Mapped[dt.datetime | None] = mapped_column(
        StrictDateTime, nullable=True
    )
    caps_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    caps_degraded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    added_at: Mapped[dt.datetime] = mapped_column(StrictDateTime, nullable=False)

    __table_args__ = (
        Index("ix_indexers_enabled", "enabled"),
    )


class ReleaseCacheRow(Base):
    """Server-side interactive-search grab cache (FRG-SRCH-014 / FRG-API-008).

    Created by this area's migration but read/written by the search/release-API
    area. Keyed ``(indexer_id, guid)`` with an ``expires_at`` housekeeping prune.
    """

    __tablename__ = "release_cache"

    id: Mapped[int] = mapped_column(StrictInteger, primary_key=True, autoincrement=True)
    indexer_id: Mapped[int] = mapped_column(
        StrictInteger,
        ForeignKey("indexers.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: Per-indexer release guid — unique only within one indexer, hence the
    #: composite cache key with ``indexer_id`` (FRG-IDX-007 identity note).
    guid: Mapped[str] = mapped_column(Text, nullable=False)
    #: The issue this search was run for (the cache's lookup dimension).
    issue_id: Mapped[int | None] = mapped_column(StrictInteger, nullable=True)
    #: Serialized decided candidate (ReleaseCandidate + decision) as JSON.
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(StrictDateTime, nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(StrictDateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("indexer_id", "guid", name="uq_release_cache_indexer_guid"),
        Index("ix_release_cache_expires_at", "expires_at"),
        Index("ix_release_cache_issue_id", "issue_id"),
    )
