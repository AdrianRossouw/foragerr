"""ORM model for ``import_history`` (FRG-PP-011).

Mirrors migration ``0006_import_history`` exactly, under the typed/sentinel-free
column conventions from :mod:`foragerr.db.base` (FRG-DB-008). The ``data`` /
``source_title`` / ``quarantine_path`` columns hold internally-generated
structured values (a per-event JSON payload, an internal source title, an
internally-constructed quarantine path), so plain ``Text`` is used throughout —
never ``SentinelFreeText`` — mirroring ``commands.payload`` and the download
models' JSON columns.

Defined in the importer area (which owns the write/read behaviour) rather than a
foundation package: change 6 is the first and only writer of this table.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from foragerr.db.base import Base, StrictDateTime, StrictInteger


class ImportHistoryRow(Base):
    """One row per pipeline outcome (FRG-PP-011).

    Keyed for join by the download-client ``download_id`` (nullable — rescan
    events have no download). ``event_type`` is one of the values in
    :data:`foragerr.importer.history.IMPORT_EVENT_TYPES`. ``data`` is a canonical
    JSON payload (reasons list, per-field evidence provenance, sizes …).
    ``quarantine_path`` is populated only for ``upgrade_replaced`` events — the
    M1 stand-in for the M2 recycle bin (design decision 8).
    """

    __tablename__ = "import_history"

    id: Mapped[int] = mapped_column(StrictInteger, primary_key=True, autoincrement=True)
    download_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    series_id: Mapped[int | None] = mapped_column(StrictInteger, nullable=True)
    issue_id: Mapped[int | None] = mapped_column(StrictInteger, nullable=True)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Per-event JSON payload — internally serialized, plain ``Text``.
    data: Mapped[str | None] = mapped_column(Text, nullable=True)
    quarantine_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(StrictDateTime, nullable=False)

    __table_args__ = (
        Index("ix_import_history_download_id", "download_id"),
        Index("ix_import_history_issue_id", "issue_id"),
        Index("ix_import_history_series_id", "series_id"),
        Index("ix_import_history_event_type", "event_type"),
        # The default sort of GET /api/v1/history (FRG-API-011); added by
        # migration 0009 (m2-daily-surfaces gate fix).
        Index("ix_import_history_created_at", "created_at"),
    )


__all__ = ["ImportHistoryRow"]
