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

import dataclasses
import datetime as dt
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from foragerr.db import queue_event
from foragerr.db.base import utcnow
from foragerr.events import Event
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
#: A CBR was converted to CBZ (FRG-PP-018): the verified-before-discard
#: format-shift at import (opt-in policy) or an on-demand per-issue/per-series
#: conversion. The ``issue_files`` row swapped path/size/page-count and the
#: original CBR was removed in the same transaction as this event.
EVENT_CONVERTED = "converted"
#: A CBR→CBZ conversion FAILED verification (or the write/promote raised) so the
#: original CBR was kept untouched (FRG-PP-018). A warning event only — the
#: surrounding import (or on-demand run) still succeeds; the file is not lost.
EVENT_CONVERT_FAILED = "convert_failed"

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
        EVENT_CONVERTED,
        EVENT_CONVERT_FAILED,
    }
)

#: Event types whose write CHANGES an issue's file presence, so the derived
#: wanted/missing list (FRG-API-012) must be re-fetched too, not just history.
#: ``imported`` / ``upgrade_replaced`` add a file; ``file_deleted`` removes one.
_FILE_PRESENCE_EVENT_TYPES: frozenset[str] = frozenset(
    {EVENT_IMPORTED, EVENT_UPGRADE_REPLACED, EVENT_FILE_DELETED}
)


@dataclasses.dataclass(frozen=True, slots=True)
class HistoryEventRecorded(Event):
    """A history row was written (FRG-API-010 WS-push source).

    Queued post-commit inside the writing transaction so a WS client can
    invalidate the history feed without polling. ``event_type``/``series_id``
    let the frontend scope the refresh; coalescing collapses an import burst
    to one frame."""

    event_type: str
    series_id: int | None


@dataclasses.dataclass(frozen=True, slots=True)
class WantedInvalidated(Event):
    """A file-presence change (import / upgrade / delete) moved an issue in or
    out of the derived wanted/missing list (FRG-API-010/FRG-API-012). Queued
    alongside :class:`HistoryEventRecorded` only for the file-presence events."""

    series_id: int | None


def _queue_history_events(
    session: AsyncSession, event_type: str, series_id: int | None
) -> None:
    """Queue the post-commit WS invalidation events for a history write.

    Always a ``history`` invalidation; ADDITIONALLY a ``wanted`` invalidation
    when the event changed a file's presence. Only fires inside a
    ``write_session`` (where post-commit delivery is wired); a bare session
    (some unit tests) is a silent no-op, never an error."""
    if session.info.get("post_commit_events") is None:
        return
    queue_event(session, HistoryEventRecorded(event_type=event_type, series_id=series_id))
    if event_type in _FILE_PRESENCE_EVENT_TYPES:
        queue_event(session, WantedInvalidated(series_id=series_id))


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
    # WS invalidation (FRG-API-010): manual/library imports and file deletes
    # emit no queue push, so without this the history/wanted screens never
    # refresh on those. Queued post-commit; discarded if the txn rolls back.
    _queue_history_events(session, event_type, series_id)
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
    ``import_failed`` events carrying a ``download_id``, the newest history row
    for that download OF ANY TYPE is consulted first: the write is skipped only
    when THAT newest row is itself a deduped-type row with an ``event_type`` AND
    canonical ``data`` string (sorted-keys JSON, so string equality is byte
    equality) matching this event exactly. Consulting the newest row of any
    type — not just the newest deduped row — is what lets an intervening
    ``imported`` / ``upgrade_replaced`` / ``grabbed`` for the same download
    break the adjacency: a real re-block AFTER an import writes a fresh row
    (``block(X) → imported → block(X)`` keeps both blocks) instead of collapsing
    into the earlier identical block. Any change in the payload — new reasons,
    new evidence — writes normally, as do events without a ``download_id`` and
    every other event type.
    """
    if download_id is not None and event_type in _DEDUPED_EVENT_TYPES:
        serialized = None if data is None else json.dumps(data, sort_keys=True)
        newest = (
            await session.execute(
                select(ImportHistoryRow)
                .where(ImportHistoryRow.download_id == download_id)
                .order_by(
                    ImportHistoryRow.created_at.desc(), ImportHistoryRow.id.desc()
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if (
            newest is not None
            and newest.event_type in _DEDUPED_EVENT_TYPES
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
    "EVENT_CONVERTED",
    "EVENT_CONVERT_FAILED",
    "EVENT_DOWNLOAD_FAILED",
    "EVENT_FILE_DELETED",
    "EVENT_FILE_RENAMED",
    "EVENT_GRABBED",
    "EVENT_IMPORTED",
    "EVENT_IMPORT_BLOCKED",
    "EVENT_IMPORT_FAILED",
    "EVENT_UPGRADE_REPLACED",
    "HistoryEventRecorded",
    "IMPORT_EVENT_TYPES",
    "SOURCE_DOWNLOAD",
    "SOURCE_LIBRARY",
    "SOURCE_MANUAL",
    "SOURCE_RESCAN",
    "WantedInvalidated",
    "all_events",
    "decode_data",
    "events_for_download",
    "events_for_issue",
    "record_event",
    "record_event_deduped",
]
