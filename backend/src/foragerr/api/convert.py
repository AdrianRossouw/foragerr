"""On-demand CBR→CBZ conversion endpoints (FRG-PP-018).

Two explicit operator triggers, mirroring the rename endpoint's transport
(FRG-PP-012 sibling): ``POST /api/v1/convert/series`` and
``POST /api/v1/convert/issue`` each enqueue the file-mutating ``convert-series``
/ ``convert-issue`` command onto the backbone (the same ``pp``-pool,
exclusivity-guarded transport every other library-mutating flow uses). Each CBR
of the target converts under verify-before-discard; already-CBZ files are skipped
as no-ops. No business logic lives here — it rides ``app.state.commands``.

Both endpoints refuse a read-only reference target up front with the uniform 409
(FRG-SER-021), so the operator gets the refusal instead of a command that the
worker then refuses out of sight; the flow keeps its own guard for a command
enqueued by another route.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from foragerr.api.command import CommandResource
from foragerr.library.read_only import (
    refuse_read_only_issues,
    refuse_read_only_series_in,
)

router = APIRouter(prefix="/convert", tags=["convert"])


class ConvertSeriesRequest(BaseModel):
    """Request body for ``POST /api/v1/convert/series``."""

    seriesId: int


class ConvertIssueRequest(BaseModel):
    """Request body for ``POST /api/v1/convert/issue``."""

    issueId: int


@router.post("/series", status_code=201, response_model=CommandResource)
async def convert_series_endpoint(
    body: ConvertSeriesRequest, request: Request
) -> CommandResource:
    """Enqueue the convert-series command (FRG-PP-018); 409 for a read-only
    reference series (FRG-SER-021)."""
    service = request.app.state.commands
    await refuse_read_only_series_in(
        request.app.state.db, body.seriesId, action="converting files"
    )
    record = await service.enqueue("convert-series", {"series_id": body.seriesId})
    return CommandResource.from_record(record)


@router.post("/issue", status_code=201, response_model=CommandResource)
async def convert_issue_endpoint(
    body: ConvertIssueRequest, request: Request
) -> CommandResource:
    """Enqueue the convert-issue command (FRG-PP-018); 409 for an issue of a
    read-only reference series (FRG-SER-021)."""
    service = request.app.state.commands
    async with request.app.state.db.read_session() as session:
        await refuse_read_only_issues(
            session, [body.issueId], action="converting files"
        )
    record = await service.enqueue("convert-issue", {"issue_id": body.issueId})
    return CommandResource.from_record(record)
