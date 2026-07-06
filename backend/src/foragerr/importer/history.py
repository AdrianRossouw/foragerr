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
#: A ComicInfo.xml tagging attempt failed AFTER the file was already imported
#: (FRG-PP-017). The file lands untagged and the import is NOT failed — this
#: warning event records the degraded outcome so the tag failure is visible.
EVENT_COMICINFO_TAG_FAILED = "comicinfo_tag_failed"

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
        EVENT_COMICINFO_TAG_FAILED,
    }
)

#: Provenance discriminators for the ``source`` column.
SOURCE_DOWNLOAD = "download"
SOURCE_RESCAN = "rescan"
#: A manual-import run (an operator resolving a blocked download or an ad-hoc
#: folder through the shared pipeline, FRG-PP-016). Data only — the decision and
#: file-op logic never read the source kind.
SOURCE_MANUAL = "manual"
#: An existing-library mass import (a confirmed library-import staging group
#: routed through the shared pipeline, FRG-IMP-023). Data only, like the rest.
SOURCE_LIBRARY = "library-import"


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


#: Event types eligible for duplicate-row suppression (RISK-040, FRG-API-011):
#: the tracking loop deliberately re-feeds a still-completed blocked/failed
#: download every cycle (retry-on-evidence-change), so only THESE outcomes can
#: legitimately recur with a byte-identical payload for one download.
_DEDUPED_EVENT_TYPES: frozenset[str] = frozenset(
    {EVENT_IMPORT_BLOCKED, EVENT_IMPORT_FAILED}
)


async def record_event_deduped(
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
) -> ImportHistoryRow | None:
    """:func:`record_event`, suppressing an identical repeated blocked outcome.

    RISK-040 (FRG-API-011): the retry loop re-runs a permanently blocked
    download through the pipeline every tracking cycle, and each run used to
    accrete one more identical ``import_blocked`` row. For ``import_blocked`` /
    ``import_failed`` events carrying a ``download_id``, the newest such row for
    that download is consulted first: when its ``event_type`` AND its canonical
    ``data`` string (sorted-keys JSON, so string equality is byte equality)
    match this event exactly, the write is skipped and ``None`` is returned.
    Any change in the payload — new reasons, new evidence — writes normally, as
    do events without a ``download_id`` and every other event type.
    """
    if download_id is not None and event_type in _DEDUPED_EVENT_TYPES:
        serialized = None if data is None else json.dumps(data, sort_keys=True)
        newest = (
            await session.execute(
                select(ImportHistoryRow)
                .where(
                    ImportHistoryRow.download_id == download_id,
                    ImportHistoryRow.event_type.in_(_DEDUPED_EVENT_TYPES),
                )
                .order_by(
                    ImportHistoryRow.created_at.desc(), ImportHistoryRow.id.desc()
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if (
            newest is not None
            and newest.event_type == event_type
            and newest.data == serialized
        ):
            return None
    return record_event(
        session,
        event_type=event_type,
        series_id=series_id,
        issue_id=issue_id,
        download_id=download_id,
        source_title=source_title,
        source=source,
        data=data,
        quarantine_path=quarantine_path,
        now=now,
    )


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
    "EVENT_COMICINFO_TAG_FAILED",
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
    "SOURCE_LIBRARY",
    "SOURCE_MANUAL",
    "SOURCE_RESCAN",
    "all_events",
    "decode_data",
    "events_for_download",
    "events_for_issue",
    "record_event",
    "record_event_deduped",
]
