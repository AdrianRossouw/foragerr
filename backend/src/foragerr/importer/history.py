"""Import-history event vocabulary, writer, and queries (FRG-PP-011).

The pipeline records one :class:`~foragerr.importer.models.ImportHistoryRow` for
every outcome — ``grabbed`` (written by the download area at grab time; the
vocabulary is shared here), ``imported`` / ``import_failed`` / ``import_blocked``
for pipeline verdicts, and ``upgrade_replaced`` / ``file_renamed`` /
``file_deleted`` / ``download_failed`` for the finer file-lifecycle events.

:func:`record_event` is the single writer. It is deliberately synchronous and
takes an already-open :class:`~sqlalchemy.ext.asyncio.AsyncSession` — never
opening its own — so a history row lands **inside the same transaction** as the
state change that produced it (FRG-PP-011 scenario 1). The event is flushed but
not committed; the caller's ``write_session()`` owns the commit, so a rollback
discards the history row exactly as it discards the outcome.

Reads (:func:`events_for_issue`, :func:`all_events`) return rows ordered by
``created_at`` then ``id`` so a download's grab → import → upgrade sequence is
stable even when several rows share a timestamp (FRG-PP-011 scenario 2).
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from foragerr.db.base import utcnow
from foragerr.importer.models import ImportHistoryRow

# --- event vocabulary (mirrors the migration's documented set) --------------

EVENT_GRABBED = "grabbed"
EVENT_IMPORTED = "imported"
EVENT_IMPORT_FAILED = "import_failed"
EVENT_IMPORT_BLOCKED = "import_blocked"
EVENT_DOWNLOAD_FAILED = "download_failed"
EVENT_FILE_DELETED = "file_deleted"
EVENT_FILE_RENAMED = "file_renamed"
EVENT_UPGRADE_REPLACED = "upgrade_replaced"

#: The full event-type vocabulary written to ``import_history.event_type``.
IMPORT_EVENT_TYPES: frozenset[str] = frozenset(
    {
        EVENT_GRABBED,
        EVENT_IMPORTED,
        EVENT_IMPORT_FAILED,
        EVENT_IMPORT_BLOCKED,
        EVENT_DOWNLOAD_FAILED,
        EVENT_FILE_DELETED,
        EVENT_FILE_RENAMED,
        EVENT_UPGRADE_REPLACED,
    }
)

#: Provenance discriminators for the ``source`` column.
SOURCE_DOWNLOAD = "download"
SOURCE_RESCAN = "rescan"


def record_event(
    session: AsyncSession,
    *,
    event_type: str,
    series_id: int | None = None,
    issue_id: int | None = None,
    download_id: str | None = None,
    source_title: str | None = None,
    source: str | None = None,
    data: dict[str, Any] | None = None,
    quarantine_path: str | None = None,
    now: dt.datetime | None = None,
) -> ImportHistoryRow:
    """Add one history row to ``session`` (FRG-PP-011). Caller owns the commit.

    ``data`` is serialized to canonical JSON (sorted keys) so the payload is
    byte-stable. Adds the row to the session and returns it; the row is not
    flushed here — the surrounding ``write_session`` flushes/commits it in the
    same transaction as the outcome it records.
    """
    if event_type not in IMPORT_EVENT_TYPES:
        raise ValueError(f"unknown import-history event_type: {event_type!r}")
    row = ImportHistoryRow(
        event_type=event_type,
        series_id=series_id,
        issue_id=issue_id,
        download_id=download_id,
        source_title=source_title,
        source=source,
        data=None if data is None else json.dumps(data, sort_keys=True),
        quarantine_path=quarantine_path,
        created_at=now or utcnow(),
    )
    session.add(row)
    return row


def decode_data(raw: str | None) -> dict[str, Any]:
    """Decode a stored ``data`` JSON payload (never raises; ``{}`` on garbage)."""
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


async def events_for_issue(
    session: AsyncSession, issue_id: int
) -> list[ImportHistoryRow]:
    """All history rows for one issue, oldest first (FRG-PP-011)."""
    result = await session.execute(
        select(ImportHistoryRow)
        .where(ImportHistoryRow.issue_id == issue_id)
        .order_by(ImportHistoryRow.created_at, ImportHistoryRow.id)
    )
    return list(result.scalars().all())


async def events_for_download(
    session: AsyncSession, download_id: str
) -> list[ImportHistoryRow]:
    """All history rows joined by one download id, oldest first (FRG-PP-011)."""
    result = await session.execute(
        select(ImportHistoryRow)
        .where(ImportHistoryRow.download_id == download_id)
        .order_by(ImportHistoryRow.created_at, ImportHistoryRow.id)
    )
    return list(result.scalars().all())


async def all_events(
    session: AsyncSession, *, limit: int | None = None
) -> list[ImportHistoryRow]:
    """The global history feed, newest first (FRG-PP-011)."""
    stmt = select(ImportHistoryRow).order_by(
        ImportHistoryRow.created_at.desc(), ImportHistoryRow.id.desc()
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


__all__ = [
    "EVENT_DOWNLOAD_FAILED",
    "EVENT_FILE_DELETED",
    "EVENT_FILE_RENAMED",
    "EVENT_GRABBED",
    "EVENT_IMPORTED",
    "EVENT_IMPORT_BLOCKED",
    "EVENT_IMPORT_FAILED",
    "EVENT_UPGRADE_REPLACED",
    "IMPORT_EVENT_TYPES",
    "SOURCE_DOWNLOAD",
    "SOURCE_RESCAN",
    "all_events",
    "decode_data",
    "events_for_download",
    "events_for_issue",
    "record_event",
]
