"""ORM models for the six change-5 tables (FRG-DL / FRG-DDL).

All six models mirror migration ``0005_download_clients`` exactly, under the
typed, sentinel-free column conventions from :mod:`foragerr.db.base`
(FRG-DB-008). ``settings``/``*_json`` columns hold internally-generated JSON, so
plain ``Text`` (mirroring ``indexers.settings`` / ``commands.payload``), never
``SentinelFreeText``.

The downloads (foundation) area owns ``DownloadClientRow`` and
``RemotePathMappingRow`` behaviorally; ``GrabHistoryRow`` / ``TrackedDownloadRow``
/ ``BlocklistRow`` are driven by the tracking area and ``DdlQueueRow`` by the ddl
area — but all are defined here so the one migration has an authoritative model
to mirror and the later areas need no schema edit.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from foragerr.db.base import Base, StrictDateTime, StrictInteger

#: Provenance discriminator values for ``source`` columns (FRG-DL-006).
SOURCE_INDEXER = "indexer"
SOURCE_DDL = "ddl"


class DownloadClientRow(Base):
    """A configured download client (FRG-DL-001/002) — the provider-pattern row.

    Mirrors :class:`foragerr.indexers.models.IndexerRow`: one table for every
    implementation, settings as validated JSON, an enable flag and priority,
    plus the remove-completed-downloads flag specific to download clients.
    """

    __tablename__ = "download_clients"

    id: Mapped[int] = mapped_column(StrictInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    #: Implementation identifier (registry key), e.g. ``sabnzbd`` / ``ddl``.
    implementation: Mapped[str] = mapped_column(Text, nullable=False)
    #: Wire protocol matched at grab dispatch: ``usenet`` (SAB) / ``ddl``.
    protocol: Mapped[str] = mapped_column(Text, nullable=False, default="usenet")
    priority: Mapped[int] = mapped_column(StrictInteger, nullable=False, default=25)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: Whether the client should be told to delete completed downloads once
    #: imported (FRG-DL-002); the tracking/import areas consult it.
    remove_completed_downloads: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    #: Validated implementation settings as canonical JSON (SecretStr values
    #: stored raw; the row loader re-registers them for redaction).
    settings: Mapped[str] = mapped_column(Text, nullable=False)
    added_at: Mapped[dt.datetime] = mapped_column(StrictDateTime, nullable=False)

    __table_args__ = (Index("ix_download_clients_enabled", "enabled"),)


class GrabHistoryRow(Base):
    """One Grabbed history row per issue, keyed by the download-id join (FRG-DL-006).

    Written by the tracking area at grab time; defined here for the migration.
    ``download_id`` is the sole join key for tracking / import / failure handling.
    """

    __tablename__ = "grab_history"

    id: Mapped[int] = mapped_column(StrictInteger, primary_key=True, autoincrement=True)
    download_id: Mapped[str] = mapped_column(Text, nullable=False)
    client_id: Mapped[int | None] = mapped_column(StrictInteger, nullable=True)
    series_id: Mapped[int | None] = mapped_column(StrictInteger, nullable=True)
    issue_id: Mapped[int | None] = mapped_column(StrictInteger, nullable=True)
    indexer_id: Mapped[int | None] = mapped_column(StrictInteger, nullable=True)
    indexer_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    guid: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    link: Mapped[str | None] = mapped_column(Text, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(StrictInteger, nullable=True)
    pub_date: Mapped[dt.datetime | None] = mapped_column(StrictDateTime, nullable=True)
    protocol: Mapped[str] = mapped_column(Text, nullable=False, default="usenet")
    #: Provenance ``indexer`` | ``ddl`` (FRG-DL-006 / FRG-DDL-001).
    source: Mapped[str] = mapped_column(Text, nullable=False, default=SOURCE_INDEXER)
    created_at: Mapped[dt.datetime] = mapped_column(StrictDateTime, nullable=False)

    __table_args__ = (
        Index("ix_grab_history_download_id", "download_id"),
        Index("ix_grab_history_issue_id", "issue_id"),
    )


class TrackedDownloadRow(Base):
    """The per-download tracking state-machine row (FRG-DL-007).

    Driven by the tracking area; defined here for the migration. ``state`` holds
    the :class:`foragerr.downloads.state.TrackedDownloadState` text value and
    ``status`` the ok/warning/error rollup.
    """

    __tablename__ = "tracked_downloads"

    id: Mapped[int] = mapped_column(StrictInteger, primary_key=True, autoincrement=True)
    download_id: Mapped[str] = mapped_column(Text, nullable=False)
    client_id: Mapped[int | None] = mapped_column(StrictInteger, nullable=True)
    client_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    protocol: Mapped[str] = mapped_column(Text, nullable=False, default="usenet")
    source: Mapped[str] = mapped_column(Text, nullable=False, default=SOURCE_INDEXER)
    state: Mapped[str] = mapped_column(Text, nullable=False, default="downloading")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="ok")
    status_messages: Mapped[str | None] = mapped_column(Text, nullable=True)
    series_id: Mapped[int | None] = mapped_column(StrictInteger, nullable=True)
    issue_id: Mapped[int | None] = mapped_column(StrictInteger, nullable=True)
    indexer_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_size: Mapped[int | None] = mapped_column(StrictInteger, nullable=True)
    remaining_size: Mapped[int | None] = mapped_column(StrictInteger, nullable=True)
    estimated_time: Mapped[int | None] = mapped_column(StrictInteger, nullable=True)
    output_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    encrypted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    added_at: Mapped[dt.datetime] = mapped_column(StrictDateTime, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(StrictDateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "client_id", "download_id", name="uq_tracked_downloads_client_download"
        ),
        Index("ix_tracked_downloads_state", "state"),
        Index("ix_tracked_downloads_download_id", "download_id"),
    )


class BlocklistRow(Base):
    """A multi-field failed-release blocklist row (FRG-DL-012).

    Written by the tracking area's failure loop; defined here for the migration.
    The multi-field match (guid + indexer + title + size + publish date for
    usenet; source URL/title for DDL) catches the same bad post resurfacing
    under a new guid.
    """

    __tablename__ = "blocklist"

    id: Mapped[int] = mapped_column(StrictInteger, primary_key=True, autoincrement=True)
    series_id: Mapped[int | None] = mapped_column(StrictInteger, nullable=True)
    issue_id: Mapped[int | None] = mapped_column(StrictInteger, nullable=True)
    source_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    guid: Mapped[str | None] = mapped_column(Text, nullable=True)
    indexer_id: Mapped[int | None] = mapped_column(StrictInteger, nullable=True)
    indexer_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(StrictInteger, nullable=True)
    publish_date: Mapped[dt.datetime | None] = mapped_column(
        StrictDateTime, nullable=True
    )
    protocol: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    download_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(StrictDateTime, nullable=False)

    __table_args__ = (
        Index("ix_blocklist_issue_id", "issue_id"),
        Index("ix_blocklist_series_id", "series_id"),
    )


class RemotePathMappingRow(Base):
    """A per-client remote→local path prefix rewrite (FRG-DL-005).

    Read by the downloads area's SAB client (and by change 6's import consumer)
    to make completed downloads importable when the client runs on another host.
    """

    __tablename__ = "remote_path_mappings"

    id: Mapped[int] = mapped_column(StrictInteger, primary_key=True, autoincrement=True)
    client_id: Mapped[int | None] = mapped_column(
        StrictInteger,
        ForeignKey("download_clients.id", ondelete="CASCADE"),
        nullable=True,
    )
    host: Mapped[str] = mapped_column(Text, nullable=False)
    remote_path: Mapped[str] = mapped_column(Text, nullable=False)
    local_path: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(StrictDateTime, nullable=False)

    __table_args__ = (Index("ix_remote_path_mappings_client_id", "client_id"),)


class DdlQueueRow(Base):
    """The built-in DDL client's persistent, single-flight queue item (FRG-DDL-007).

    Driven by the ddl area; defined here for the migration. Items survive restart
    (SCHED orphan recovery re-queues in-flight ones) and are projected through
    ``get_items()`` into the common tracked-download view.
    """

    __tablename__ = "ddl_queue"

    id: Mapped[int] = mapped_column(StrictInteger, primary_key=True, autoincrement=True)
    download_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    series_id: Mapped[int | None] = mapped_column(StrictInteger, nullable=True)
    issue_id: Mapped[int | None] = mapped_column(StrictInteger, nullable=True)
    provider_id: Mapped[int | None] = mapped_column(StrictInteger, nullable=True)
    post_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_size: Mapped[int | None] = mapped_column(StrictInteger, nullable=True)
    bytes_received: Mapped[int] = mapped_column(StrictInteger, nullable=False, default=0)
    current_host: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    selected_link_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    failed_hosts_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(StrictInteger, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(StrictDateTime, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(StrictDateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("download_id", name="uq_ddl_queue_download_id"),
        Index("ix_ddl_queue_status", "status"),
    )


__all__ = [
    "SOURCE_DDL",
    "SOURCE_INDEXER",
    "BlocklistRow",
    "DdlQueueRow",
    "DownloadClientRow",
    "GrabHistoryRow",
    "RemotePathMappingRow",
    "TrackedDownloadRow",
]
