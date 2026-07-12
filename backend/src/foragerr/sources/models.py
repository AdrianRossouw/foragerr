"""ORM models for the store-source domain (FRG-SRC-001/003).

``SourceRow`` is the provider-pattern configuration row (design decision 1): one
``sources`` table for every store type, settings as validated JSON (the
``_simpleauth_sess`` cookie a TOP-LEVEL ``SecretStr`` → keystore-encrypted
automatically), a connection state, the auto-sync toggle, and last-sync
metadata.

``SourceEntitlementRow`` (table ``source_entitlements``) is the *inventory* — the
list of items the account owns. It is keyed by the store-native identity
(``gamekey`` + subproduct ``machine_name``) so an entitlement survives a title
edit and a re-sync is an idempotent diff (design decision 1 "store-native key as
identity"). Review status (``new`` / ``matched`` / ``ignored``) and download
state live on SEPARATE axes (design decision 2).

Uses the typed, sentinel-free column conventions from :mod:`foragerr.db.base`
(FRG-DB-008). ``settings`` / ``*_json`` are internally-generated JSON, so plain
``Text`` (mirroring ``indexers.settings``), never ``SentinelFreeText``.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from foragerr.db.base import Base, StrictDateTime, StrictInteger

#: The connection-state values a source moves between (FRG-SRC-001/005).
CONNECTION_STATES = ("connected", "expired", "disconnected")

#: Content-classification values on the entitlement (FRG-SRC-003). Non-comic
#: items are kept as ``other`` and shown on demand, never dropped.
CLASSIFICATIONS = ("comic", "other")

#: Review-status axis values (design decision 2). ``download_state`` is a
#: separate axis (the existing-pipeline progress), surfaced in Activity.
REVIEW_STATUSES = ("new", "matched", "ignored")


class SourceRow(Base):
    """A connected store source (FRG-SRC-001)."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(StrictInteger, primary_key=True, autoincrement=True)
    #: Store type / implementation identifier (registry key), e.g. ``humble``.
    type: Mapped[str] = mapped_column(Text, nullable=False)
    #: Display name for the source (defaults to the store label).
    name: Mapped[str] = mapped_column(Text, nullable=False)
    #: Validated implementation settings as canonical JSON. TOP-LEVEL
    #: ``SecretStr`` values (the cookie) are stored ``enc:v1:``-encrypted; the
    #: row loader re-registers them for redaction (FRG-SRC-002).
    settings: Mapped[str] = mapped_column(Text, nullable=False)
    #: ``connected`` / ``expired`` / ``disconnected`` (FRG-SRC-001/005).
    connection_state: Mapped[str] = mapped_column(
        Text, nullable=False, default="disconnected"
    )
    #: Per-source *Auto-sync new purchases* toggle — ships OFF (owner
    #: 2026-07-11); the confident-match auto-accept path (FRG-SRC-004) reads it.
    auto_sync: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_sync_at: Mapped[dt.datetime | None] = mapped_column(
        StrictDateTime, nullable=True
    )
    #: Short human-readable summary of the last sync run (or its failure).
    last_sync_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    added_at: Mapped[dt.datetime] = mapped_column(StrictDateTime, nullable=False)

    __table_args__ = (Index("ix_sources_type", "type"),)


class SourceEntitlementRow(Base):
    """One owned store item (subproduct) — the reviewable inventory (FRG-SRC-003).

    Identity is the store-native key ``(source_id, gamekey, machine_name)`` so a
    re-sync diffs idempotently and never duplicates an item.
    """

    __tablename__ = "source_entitlements"

    id: Mapped[int] = mapped_column(StrictInteger, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        StrictInteger,
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: Store-native diff identity — gamekey (the order) + subproduct machine_name.
    gamekey: Mapped[str] = mapped_column(Text, nullable=False)
    machine_name: Mapped[str] = mapped_column(Text, nullable=False)
    #: Sanitized display title (FRG-META-014 pattern applied at sync).
    human_name: Mapped[str] = mapped_column(Text, nullable=False)
    publisher: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: ``comic`` | ``other`` (FRG-SRC-003). Non-comic items are retained.
    classification: Mapped[str] = mapped_column(Text, nullable=False)
    #: ``new`` | ``matched`` | ``ignored`` — the review axis (design decision 2).
    review_status: Mapped[str] = mapped_column(
        Text, nullable=False, default="new"
    )
    #: Download/import-progress axis, separate from review status (design
    #: decision 2): ``None`` (never grabbed) → ``queued`` → ``fetching`` →
    #: ``verifying`` → ``import_pending`` → ``imported`` | ``import_blocked`` |
    #: ``failed`` (FRG-SRC-006). The entitlement only becomes ``imported`` once
    #: the completed-download drain actually lands the file in the library
    #: (``import_pending`` bridges handoff → durable import); ``import_blocked`` /
    #: ``failed`` reflect a rejected or failed import. Cleared to ``None`` when the
    #: item is ignored.
    download_state: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The last grab failure reason (FRG-SRC-006) — the per-entitlement
    #: failed-download surface. Set alongside ``download_state = "failed"``;
    #: cleared when a retry re-queues the grab. ``None`` when not failed.
    download_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The preferred grabbable copy's API metadata (never the signed URL —
    #: re-fetched fresh at grab time, design decision 8).
    preferred_format: Mapped[str | None] = mapped_column(Text, nullable=True)
    md5: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_size: Mapped[int | None] = mapped_column(StrictInteger, nullable=True)
    filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Every available download option as JSON [{name, md5, file_size, platform}].
    formats_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    #: Proposed-match seam (worker A2 computes the ranking; ``None`` until then).
    proposed_series_id: Mapped[int | None] = mapped_column(
        StrictInteger, nullable=True
    )
    proposed_match_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Operator-chosen match target (review workflow; ``None`` until matched).
    matched_series_id: Mapped[int | None] = mapped_column(
        StrictInteger, nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(StrictDateTime, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(StrictDateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "gamekey",
            "machine_name",
            name="uq_source_entitlements_native_key",
        ),
        Index(
            "ix_source_entitlements_source_review",
            "source_id",
            "review_status",
        ),
        Index(
            "ix_source_entitlements_source_classification",
            "source_id",
            "classification",
        ),
    )
