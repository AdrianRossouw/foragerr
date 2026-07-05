"""Command backbone transport: ``POST``/``GET /api/v1/command`` (FRG-API-001,
FRG-API-002, FRG-SCHED-007).

Rides ``app.state.commands``/``app.state.db`` — consumes, never
re-implements, the command backbone (design decision 10). The paged list
endpoint demonstrates the shared paging-envelope helper
(:mod:`foragerr.api.paging`), sortable by ``queued_at``/``status``/``name``.
Force-running a scheduled task (FRG-SCHED-007) rides this same transport: a
scheduled task's command name is just another ``name`` value to ``POST``.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from sqlalchemy import select

from foragerr.api.errors import ApiError
from foragerr.api.paging import paginate
from foragerr.commands import CommandRecord, CommandValidationError
from foragerr.db import CommandRow

router = APIRouter(prefix="/command", tags=["command"])

#: Whitelisted sort keys -> fixed column expressions (FRG-API-002); the
#: client-supplied sortKey string is never interpolated into SQL.
_SORT_WHITELIST = {
    "queued_at": CommandRow.queued_at,
    "status": CommandRow.status,
    "name": CommandRow.name,
}


class CommandCreate(BaseModel):
    """Request body for ``POST /api/v1/command``."""

    name: str
    payload: dict[str, Any] | None = None
    priority: int | None = None


class CommandResource(BaseModel):
    """A command resource (FRG-API-002: integer ``id``, JSON body)."""

    id: int
    name: str
    status: str
    priority: int
    workload_class: str
    exclusivity_group: str | None
    payload: dict[str, Any]
    triggered_by: str
    queued_at: dt.datetime
    started_at: dt.datetime | None
    finished_at: dt.datetime | None
    result: str | None
    error: str | None

    @classmethod
    def from_record(cls, record: CommandRecord) -> "CommandResource":
        return cls(
            id=record.id,
            name=record.name,
            status=record.status,
            priority=record.priority,
            workload_class=record.workload_class,
            exclusivity_group=record.exclusivity_group,
            payload=record.payload,
            triggered_by=record.triggered_by,
            queued_at=record.queued_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
            result=record.result,
            error=record.error,
        )

    @classmethod
    def from_row(cls, row: CommandRow) -> "CommandResource":
        return cls(
            id=row.id,
            name=row.name,
            status=row.status,
            priority=row.priority,
            workload_class=row.workload_class,
            exclusivity_group=row.exclusivity_group,
            payload=json.loads(row.payload),
            triggered_by=row.triggered_by,
            queued_at=row.queued_at,
            started_at=row.started_at,
            finished_at=row.finished_at,
            result=row.result,
            error=row.error,
        )


class CommandPage(BaseModel):
    """Paging envelope (FRG-API-002) specialized for command resources."""

    page: int
    pageSize: int
    sortKey: str
    sortDirection: str
    totalRecords: int
    records: list[CommandResource]


@router.post("", status_code=201, response_model=CommandResource)
async def create_command(body: CommandCreate, request: Request) -> CommandResource:
    """Enqueue a command (FRG-API-001/002). Dedup is observable: resubmitting
    an equal-bodied command already queued/started returns the SAME id
    instead of creating a duplicate (FRG-SCHED-003, exercised via this
    transport)."""
    service = request.app.state.commands
    try:
        record = await service.enqueue(body.name, body.payload, priority=body.priority)
    except CommandValidationError as exc:
        raise ApiError(400, str(exc), field="name") from exc
    return CommandResource.from_record(record)


@router.get("", response_model=CommandPage)
async def list_commands(
    request: Request,
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=200),
    sortKey: str = Query("queued_at"),
    sortDirection: str = Query("desc"),
) -> CommandPage:
    """Paged command list (FRG-API-002 paging-envelope demonstration)."""
    db = request.app.state.db
    async with db.read_session() as session:
        result = await paginate(
            session,
            stmt=select(CommandRow),
            page=page,
            page_size=pageSize,
            sort_key=sortKey,
            sort_direction=sortDirection,
            whitelist=_SORT_WHITELIST,
        )
    result["records"] = [CommandResource.from_row(row) for row in result["records"]]
    return CommandPage(**result)


@router.get("/{command_id}", response_model=CommandResource)
async def get_command(command_id: int, request: Request) -> CommandResource:
    """Command status lookup; 404 in the uniform error shape when absent."""
    service = request.app.state.commands
    record = await service.get(command_id)
    if record is None:
        raise ApiError(404, f"command {command_id} not found")
    return CommandResource.from_record(record)
