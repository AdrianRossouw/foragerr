"""The log-records HTTP surface: ``GET /api/v1/log`` (FRG-API-021).

A paged, newest-first read over the in-memory ring buffer installed by
``foragerr.logging_buffer.install_log_buffer`` at startup (``app.state.log_buffer``).
Not a database read (unlike ``history``/``queue``): there is no SQL to
paginate, so filtering/slicing happens over the buffer's in-memory snapshot.
The paging envelope shape is still the shared one (FRG-API-002), built with
the same ``envelope()`` helper the DB-backed list endpoints use.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from foragerr.api.errors import ApiError
from foragerr.api.paging import envelope
from foragerr.logging_buffer import BufferedLogRecord, RingBufferHandler

router = APIRouter(prefix="/log", tags=["log"])

#: Minimum-level filter values accepted by the ``level`` query param, low to
#: high. CRITICAL records still pass an ``ERROR`` filter (numeric level
#: comparison below) even though CRITICAL is not itself an accepted filter
#: value — Sonarr-style "at or above" filtering.
_MIN_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")

#: Maps an accepted query-param level name to its numeric stdlib threshold.
#: Only used to PARSE the ``level`` query param — filtering itself compares
#: against each buffered record's own ``levelno`` (captured at emit time via
#: ``record.levelno``), so a custom-level record (a levelname not in this
#: map, e.g. via ``logging.log(25, ...)``) still compares correctly instead
#: of falling through to 0 and vanishing under any active filter.
_LEVEL_VALUE = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
}


class LogEntry(BaseModel):
    """One log record as the API exposes it (FRG-API-021)."""

    time: dt.datetime
    level: str
    logger: str
    message: str


class LogPage(BaseModel):
    """Paging envelope (FRG-API-002) specialized for log entries."""

    page: int
    pageSize: int
    sortKey: str
    sortDirection: str
    totalRecords: int
    records: list[LogEntry]


def _to_entry(record: BufferedLogRecord) -> LogEntry:
    return LogEntry(
        time=record.time, level=record.level, logger=record.logger, message=record.message
    )


@router.get("", response_model=LogPage)
async def list_log(
    request: Request,
    page: int = Query(1, ge=1),
    pageSize: int = Query(50, ge=1, le=200),  # shared server cap, FRG-NFR-003
    level: str | None = Query(
        None, description="Minimum level (DEBUG, INFO, WARNING, ERROR)."
    ),
    logger: str | None = Query(
        None, description="Dotted logger-name prefix filter."
    ),
) -> LogPage:
    """Paged, newest-first read over the in-memory log buffer (FRG-API-021).

    An empty buffer (fresh process, or the ring-buffer handler was never
    installed) returns an empty page with ``totalRecords=0`` — never an
    error (the "empty buffer after restart" scenario). Sort is fixed
    (newest first by time); this resource has no client-selectable sort
    key, unlike the DB-backed list endpoints.
    """
    if level is not None and level.upper() not in _MIN_LEVELS:
        raise ApiError(
            400,
            f"unknown level {level!r}; must be one of {_MIN_LEVELS}",
            field="level",
        )
    threshold = _LEVEL_VALUE[level.upper()] if level is not None else None

    handler: RingBufferHandler | None = getattr(request.app.state, "log_buffer", None)
    records = handler.snapshot() if handler is not None else []
    records.reverse()  # buffer is oldest-first; the API is newest-first

    if threshold is not None:
        records = [r for r in records if r.levelno >= threshold]
    if logger:
        records = [r for r in records if r.logger.startswith(logger)]

    total = len(records)
    start = (page - 1) * pageSize
    page_records = records[start : start + pageSize]

    result = envelope(
        page=page,
        page_size=pageSize,
        sort_key="time",
        sort_direction="desc",
        total_records=total,
        records=[_to_entry(r) for r in page_records],
    )
    return LogPage(**result)


__all__ = ["router"]
