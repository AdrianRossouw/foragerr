"""The queue HTTP surface: ``GET``/``DELETE /api/v1/queue`` (FRG-DL-008, FRG-API-007).

The user-facing queue is assembled EXCLUSIVELY from ``tracked_downloads`` joined
to the library — no user-facing request ever polls a download client directly
(the load-bearing property). A grabbed release therefore appears with its
``downloading`` state within one tracking cycle rather than on demand, and
``import_pending`` / ``import_blocked`` items stay visible instead of vanishing
when the client reports completed.

``DELETE /queue/{id}`` is the one queue ACTION (not a read): it removes the item
from tracking, instructs the download client to remove it (and its data when
asked), and writes a blocklist row when ``blocklist=true`` — the manual-remove
counterpart of the automatic failure loop.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from sqlalchemy import select

from foragerr.api.errors import ApiError
from foragerr.api.paging import load_issue_map, load_series_map, paginate
from foragerr.db import utcnow
from foragerr.downloads.models import (
    GrabHistoryRow,
    TrackedDownloadRow,
)
from foragerr.downloads.state import TrackedDownloadState
from foragerr.downloads.tracking import (
    build_client_for_id,
    decode_messages,
    write_blocklist_row,
)
from foragerr.library.models import IssueRow, SeriesRow

router = APIRouter(prefix="/queue", tags=["queue"])

#: States hidden from the queue: fully done or operator-ignored. Everything else
#: — downloading, import_blocked, import_pending, failed_pending, failed — stays
#: visible so the user sees in-flight, awaiting-import, and just-failed items.
_HIDDEN_STATES = (
    TrackedDownloadState.IMPORTED.value,
    TrackedDownloadState.IGNORED.value,
)

_SORT_WHITELIST = {
    "added_at": TrackedDownloadRow.added_at,
    "updated_at": TrackedDownloadRow.updated_at,
    "state": TrackedDownloadRow.state,
    "status": TrackedDownloadRow.status,
}


class QueueSeries(BaseModel):
    id: int
    title: str


class QueueIssue(BaseModel):
    id: int
    issueNumber: str | None
    title: str | None


class QueueResource(BaseModel):
    """One tracked download as the queue exposes it (FRG-API-007)."""

    id: int
    seriesId: int | None
    issueId: int | None
    series: QueueSeries | None
    issue: QueueIssue | None
    size: int | None
    sizeleft: int | None
    status: str
    state: str
    statusMessages: list[str]
    downloadId: str
    protocol: str
    downloadClient: str | None
    indexer: str | None
    outputPath: str | None
    estimatedCompletion: dt.datetime | None


class QueuePage(BaseModel):
    """Paging envelope (FRG-API-002) specialized for queue resources."""

    page: int
    pageSize: int
    sortKey: str
    sortDirection: str
    totalRecords: int
    records: list[QueueResource]


def _estimated_completion(
    row: TrackedDownloadRow, now: dt.datetime
) -> dt.datetime | None:
    """When the client expects the download to finish, or ``None``."""
    if (
        row.estimated_time is None
        or row.state != TrackedDownloadState.DOWNLOADING.value
    ):
        return None
    return now + dt.timedelta(seconds=row.estimated_time)


def _to_resource(
    row: TrackedDownloadRow,
    series: SeriesRow | None,
    issue: IssueRow | None,
    now: dt.datetime,
) -> QueueResource:
    return QueueResource(
        id=row.id,
        seriesId=row.series_id,
        issueId=row.issue_id,
        series=QueueSeries(id=series.id, title=series.title) if series else None,
        issue=(
            QueueIssue(id=issue.id, issueNumber=issue.issue_number, title=issue.title)
            if issue
            else None
        ),
        size=row.total_size,
        sizeleft=row.remaining_size,
        status=row.status,
        state=row.state,
        statusMessages=decode_messages(row.status_messages),
        downloadId=row.download_id,
        protocol=row.protocol,
        downloadClient=row.client_name,
        indexer=row.indexer_name,
        outputPath=row.output_path,
        estimatedCompletion=_estimated_completion(row, now),
    )


@router.get("", response_model=QueuePage)
async def list_queue(
    request: Request,
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=200),
    sortKey: str = Query("added_at"),
    sortDirection: str = Query("desc"),
) -> QueuePage:
    """Paged queue built ONLY from ``tracked_downloads`` (FRG-DL-008, FRG-API-007).

    Never makes a live download-client call at request time; the state shown is
    whatever the tracking refresh last persisted."""
    db = request.app.state.db
    now = utcnow()
    async with db.read_session() as session:
        result = await paginate(
            session,
            stmt=select(TrackedDownloadRow).where(
                TrackedDownloadRow.state.notin_(_HIDDEN_STATES)
            ),
            page=page,
            page_size=pageSize,
            sort_key=sortKey,
            sort_direction=sortDirection,
            whitelist=_SORT_WHITELIST,
            # The default added_at sort ties for downloads grabbed in one
            # cycle; the id tiebreak keeps the pages a stable partition.
            tiebreak=TrackedDownloadRow.id,
        )
        rows: list[TrackedDownloadRow] = result["records"]
        series_by_id = await load_series_map(session, {r.series_id for r in rows})
        issue_by_id = await load_issue_map(session, {r.issue_id for r in rows})
    result["records"] = [
        _to_resource(
            row, series_by_id.get(row.series_id), issue_by_id.get(row.issue_id), now
        )
        for row in rows
    ]
    return QueuePage(**result)


@router.delete("/{queue_id}", status_code=200)
async def delete_queue_item(
    queue_id: int,
    request: Request,
    blocklist: bool = Query(False),
    deleteData: bool = Query(False),
) -> dict[str, object]:
    """Manually remove a queue item (FRG-DL-008, FRG-API-007, FRG-DL-010).

    Removes the tracked row, instructs the client to remove the download (and its
    data when ``deleteData=true``), and writes a blocklist row when
    ``blocklist=true``. The client removal is best-effort — an unreachable client
    never blocks the queue cleanup — but blocklisting + de-tracking always happen.

    An item that is actively ``importing`` is refused (409): the post-processing
    drain holds it and is moving its files, so deleting the client's data now
    would yank files out from under an in-flight import. De-tracking is done
    FIRST under a write-lock guard that excludes ``importing`` (so a drain cannot
    claim it in the window), and only THEN is the client told to drop the data —
    once de-tracked, no drain can pick the item up.
    """
    db = request.app.state.db
    settings = request.app.state.settings
    now = utcnow()
    importing = TrackedDownloadState.IMPORTING.value

    async with db.read_session() as session:
        row = await session.get(TrackedDownloadRow, queue_id)
        if row is None:
            raise ApiError(404, f"queue item {queue_id} not found")
        if row.state == importing:
            raise ApiError(
                409, "import in progress for this item; try again once it completes"
            )
        download_id = row.download_id
        client_id = row.client_id

    # De-track first, guarded against a drain that flipped it to importing between
    # our read and this write. Once the row is gone the drain can never claim it.
    async with db.write_session() as session:
        row = await session.get(TrackedDownloadRow, queue_id)
        if row is None:
            raise ApiError(404, f"queue item {queue_id} not found")
        if row.state == importing:
            raise ApiError(
                409, "import in progress for this item; try again once it completes"
            )
        if blocklist:
            await _write_manual_blocklist(session, row, now)
        await session.delete(row)

    # Safe now: the item is de-tracked, so deleting client data cannot race a drain.
    await _instruct_client_remove(db, settings, client_id, download_id, deleteData)

    return {"id": queue_id, "removed": True, "blocklisted": blocklist}


async def _instruct_client_remove(
    db, settings, client_id: int | None, download_id: str, delete_data: bool
) -> None:
    """Best-effort: tell the download client to drop this item (and its data)."""
    if client_id is None:
        return
    try:
        client = await build_client_for_id(db, client_id, settings=settings)
        if client is None:
            return
        for item in await client.get_items():
            if item.download_id == download_id:
                await client.remove(item, delete_data)
                return
    except Exception:  # noqa: BLE001 — client removal must not block de-tracking
        import logging

        logging.getLogger("foragerr.api.queue").warning(
            "queue: client removal failed; item still de-tracked",
            extra={"client_id": client_id, "download_id": download_id},
        )


async def _write_manual_blocklist(
    session, row: TrackedDownloadRow, now: dt.datetime
) -> None:
    """Blocklist a manually-removed release using its grab data (FRG-DL-012).

    Delegates to the shared :func:`write_blocklist_row` so the manual-remove and
    automatic-failure paths build the identical multi-field match key."""
    grabs = (
        (
            await session.execute(
                select(GrabHistoryRow).where(
                    GrabHistoryRow.download_id == row.download_id
                )
            )
        )
        .scalars()
        .all()
    )
    write_blocklist_row(
        session,
        row=row,
        grabs=grabs,
        now=now,
        message="manually removed from the queue and blocklisted",
    )


__all__ = ["router"]
