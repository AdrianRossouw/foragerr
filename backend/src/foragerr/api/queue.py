"""The queue HTTP surface: ``GET``/``DELETE``/``POST`` (FRG-DL-008, FRG-API-007).

The user-facing queue is assembled EXCLUSIVELY from ``tracked_downloads`` joined
to the library — no user-facing request ever polls a download client directly
(the load-bearing property). A grabbed release therefore appears with its
``downloading`` state within one tracking cycle rather than on demand, and
``import_pending`` / ``import_blocked`` items stay visible instead of vanishing
when the client reports completed.

``DELETE /queue/{id}`` is the one queue ACTION (not a read): it removes the item
from tracking, instructs the download client to remove it (and its data when
asked), and writes a blocklist row when ``blocklist=true`` — the manual-remove
counterpart of the automatic failure loop. ``POST /queue/remove`` is that same
action over many ids, reporting per-row rather than failing the batch.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, model_validator
from sqlalchemy import func, select

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
    #: How many queue rows are terminally ``failed``, across ALL pages — the
    #: reach of ``POST /queue/remove {scope: "failed"}``. A page-derived count
    #: would understate a backlog longer than one page, so the client cannot
    #: compute this from ``records``.
    failedRecords: int
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
        result["failedRecords"] = (
            await session.execute(
                select(func.count())
                .select_from(TrackedDownloadRow)
                .where(TrackedDownloadRow.state == TrackedDownloadState.FAILED.value)
            )
        ).scalar_one()
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
    await _instruct_clients_remove(db, settings, [(client_id, download_id)], deleteData)

    return {"id": queue_id, "removed": True, "blocklisted": blocklist}


#: Upper bound on one bulk remove. A queue page is 20 rows and the cap is far
#: above any select-all, so it never truncates real work — it bounds the
#: best-effort client calls one request can fan out into.
_MAX_BULK_REMOVE = 500


class QueueRemoveRequest(BaseModel):
    """Body of ``POST /queue/remove`` (FRG-DL-008).

    Two mutually exclusive forms name the targets. ``ids`` removes exactly the
    rows listed. ``scope="failed"`` removes every terminally-failed row the
    QUEUE holds, whichever page it is on — the operator asking to clear the
    failure backlog is not asking to clear the twenty rows they can see, and a
    client that could only send the ids it has loaded would silently under-
    deliver on a backlog longer than one page.
    """

    ids: list[int] | None = None
    scope: Literal["failed"] | None = None
    blocklist: bool = False
    deleteData: bool = False

    @model_validator(mode="after")
    def _exactly_one_target_form(self) -> QueueRemoveRequest:
        if (self.ids is None) == (self.scope is None):
            raise ValueError("name the targets with exactly one of ids or scope")
        if self.ids is not None:
            if not self.ids:
                raise ValueError("ids must name at least one queue item")
            if len(self.ids) > _MAX_BULK_REMOVE:
                raise ValueError(f"ids must name at most {_MAX_BULK_REMOVE} queue items")
        return self


@router.post("/remove", status_code=200)
async def remove_queue_items(
    body: QueueRemoveRequest, request: Request
) -> dict[str, object]:
    """Remove many queue items in one request (FRG-DL-008, FRG-DL-010).

    Every targeted row gets the single ``DELETE``'s exact semantics — an
    ``importing`` row is refused, ``blocklist`` writes the shared multi-field
    key, client removal is best-effort — but a refusal lands in ``errors``
    under that id instead of failing the batch: one stuck row must never veto a
    queue cleanup.

    De-tracking runs in ONE write transaction, so the ``importing`` guard is
    read inside the transaction that deletes (a drain cannot claim a row in a
    read-then-write window). The ``scope="failed"`` selection is made inside
    that same transaction, so the set removed is the set that was failed at
    commit time rather than a set some earlier read reported. Client removals
    run only AFTER the transaction commits: once a row is de-tracked no drain
    can pick it up, so deleting its data cannot race an in-flight import. A
    client removal that fails is logged and left out of ``errors`` — the row IS
    de-tracked, which is what the caller asked about.
    """
    db = request.app.state.db
    settings = request.app.state.settings
    now = utcnow()
    importing = TrackedDownloadState.IMPORTING.value

    errors: dict[int, str] = {}
    removed: list[tuple[int | None, str]] = []
    async with db.write_session() as session:
        if body.scope == "failed":
            targets: list[tuple[int, TrackedDownloadRow | None]] = [
                (row.id, row)
                for row in (
                    await session.execute(
                        select(TrackedDownloadRow).where(
                            TrackedDownloadRow.state
                            == TrackedDownloadState.FAILED.value
                        )
                    )
                )
                .scalars()
                .all()
            ]
        else:
            # dict.fromkeys: a repeated id is one removal, not a second 404.
            targets = [
                (queue_id, await session.get(TrackedDownloadRow, queue_id))
                for queue_id in dict.fromkeys(body.ids or ())
            ]

        for queue_id, row in targets:
            if row is None:
                errors[queue_id] = f"queue item {queue_id} not found"
                continue
            if row.state == importing:
                errors[queue_id] = (
                    "import in progress for this item; try again once it completes"
                )
                continue
            if body.blocklist:
                await _write_manual_blocklist(session, row, now)
            removed.append((row.client_id, row.download_id))
            await session.delete(row)

    await _instruct_clients_remove(db, settings, removed, body.deleteData)

    return {"applied": len(removed), "errors": errors}


async def _instruct_clients_remove(
    db,
    settings,
    removed: list[tuple[int | None, str]],
    delete_data: bool,
) -> None:
    """Best-effort: tell each download client to drop the items it owns.

    Grouped by client and listed ONCE per client, not once per row: a client's
    item listing is a full remote round-trip (SABnzbd needs two), so a per-row
    loop turns a twenty-row clear into forty requests against a service that is
    already the slowest thing in the path.
    """
    by_client: dict[int, list[str]] = {}
    for client_id, download_id in removed:
        if client_id is not None:
            by_client.setdefault(client_id, []).append(download_id)

    for client_id, download_ids in by_client.items():
        await _instruct_client_remove(db, settings, client_id, download_ids, delete_data)


async def _instruct_client_remove(
    db, settings, client_id: int, download_ids: list[str], delete_data: bool
) -> None:
    """Best-effort removal of every named download from one client."""
    logger = logging.getLogger("foragerr.api.queue")
    wanted = set(download_ids)
    try:
        client = await build_client_for_id(db, client_id, settings=settings)
        if client is None:
            return
        items = await client.get_items()
    except Exception:  # noqa: BLE001 — client removal must not block de-tracking
        logger.warning(
            "queue: client unreachable; items still de-tracked",
            extra={"client_id": client_id, "download_ids": sorted(wanted)},
        )
        return

    for item in items:
        if item.download_id not in wanted:
            continue
        try:
            await client.remove(item, delete_data)
        except Exception:  # noqa: BLE001 — one stuck item must not strand the rest
            logger.warning(
                "queue: client removal failed; item still de-tracked",
                extra={"client_id": client_id, "download_id": item.download_id},
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
