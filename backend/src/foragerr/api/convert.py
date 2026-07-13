"""On-demand CBR→CBZ conversion endpoints (FRG-PP-018).

Two explicit operator triggers, mirroring the rename endpoint's transport
(FRG-PP-012 sibling): ``POST /api/v1/convert/series`` and
``POST /api/v1/convert/issue`` each enqueue the file-mutating ``convert-series``
/ ``convert-issue`` command onto the backbone (the same ``pp``-pool,
exclusivity-guarded transport every other library-mutating flow uses). Each CBR
of the target converts under verify-before-discard; already-CBZ files are skipped
as no-ops. No business logic lives here — it rides ``app.state.commands``.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from foragerr.api.command import CommandResource

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
    """Enqueue the convert-series command (FRG-PP-018)."""
    service = request.app.state.commands
    record = await service.enqueue("convert-series", {"series_id": body.seriesId})
    return CommandResource.from_record(record)


@router.post("/issue", status_code=201, response_model=CommandResource)
async def convert_issue_endpoint(
    body: ConvertIssueRequest, request: Request
) -> CommandResource:
    """Enqueue the convert-issue command (FRG-PP-018)."""
    service = request.app.state.commands
    record = await service.enqueue("convert-issue", {"issue_id": body.issueId})
    return CommandResource.from_record(record)
