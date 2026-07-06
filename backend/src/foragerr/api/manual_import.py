"""Manual-import endpoints (FRG-API-015).

``GET /api/v1/manual-import?path=<abs>`` **or** ``?downloadId=<id>`` lists the
candidate files under a folder (or a blocked download) with their would-be import
decisions, rejection reasons, suggested mapping, and embedded-metadata summary —
computed through the shared pipeline, touching no disk beyond archive inspection.

``POST /api/v1/manual-import`` accepts operator-corrected mappings
(``series``/``issue``/``format`` overrides per file), validates and confines each
path, and enqueues a ``manual-import`` command on the pp-pool — the same
exclusivity-guarded transport ``rename-series`` uses — returning ``201`` with a
``CommandResource``. Execution runs the FULL decision set over each candidate, so
the API exposes no "force" that skips ``ArchiveValidSpec`` / ``FreeSpaceSpec`` /
``JunkFilterSpec``; a mapping targeting a corrupt / below-floor / no-space file is
reported blocked/failed with its reason, the same pipeline and history as an
automatic import.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel

from foragerr.api.command import CommandResource
from foragerr.api.errors import ApiError
from foragerr.commands import CommandValidationError
from foragerr.commands.service import daemon_offload
from foragerr.downloads.manual_import import (
    ManualImportError,
    confine_under_roots,
    execute_roots,
    list_manual_candidates,
)

router = APIRouter(tags=["manual-import"])


class EmbeddedSummary(BaseModel):
    """The embedded ComicInfo read summary for one candidate (FRG-IMP-024)."""

    comicInfoPresent: bool
    cvIssueId: int | None
    verified: bool


class ManualImportEntry(BaseModel):
    """One candidate file's would-be verdict (FRG-API-015)."""

    path: str
    name: str
    size: int
    folder: str | None
    approved: bool
    rejections: list[str]
    suggestedSeriesId: int | None
    suggestedIssueId: int | None
    format: str | None
    embedded: EmbeddedSummary


class ManualImportFile(BaseModel):
    """One picked file's corrected mapping in a manual-import execute request."""

    path: str
    seriesId: int | None = None
    issueId: int | None = None
    format: str | None = None
    #: Set by the overlay when the row came from a blocked download, so execute
    #: rebuilds the file through the same download-shaped source and the same
    #: specs (esp. already-imported) evaluate as the listing did (FRG-PP-016).
    downloadId: str | None = None


class ManualImportRequest(BaseModel):
    """Request body for ``POST /api/v1/manual-import``."""

    files: list[ManualImportFile]


@router.get("/manual-import", response_model=list[ManualImportEntry])
async def list_manual_import_endpoint(
    request: Request,
    response: Response,
    path: str | None = Query(None),
    downloadId: str | None = Query(None),
) -> list[ManualImportEntry]:
    """List candidate files with their decisions (FRG-API-015). Touches no disk
    beyond inspection; an unreadable path or unknown download is a typed error.

    The per-candidate archive inspection is offloaded off the event loop, and the
    list is capped: when the folder exceeded the cap the response is truncated and
    an ``X-Manual-Import-Truncated: true`` header flags it."""
    db = request.app.state.db
    settings = request.app.state.settings
    try:
        listing = await list_manual_candidates(
            db, settings, path=path, download_id=downloadId, offload=daemon_offload
        )
    except ManualImportError as exc:
        raise ApiError(exc.status_code, exc.message) from exc
    if listing.truncated:
        response.headers["X-Manual-Import-Truncated"] = "true"
    return [
        ManualImportEntry(
            path=entry.candidate.local_path,
            name=entry.candidate.file_name,
            size=entry.candidate.size,
            folder=entry.candidate.folder_name,
            approved=entry.approved,
            rejections=list(entry.rejections),
            suggestedSeriesId=entry.suggested_series_id,
            suggestedIssueId=entry.suggested_issue_id,
            format=entry.format,
            embedded=EmbeddedSummary(
                comicInfoPresent=entry.comic_info_present,
                cvIssueId=entry.embedded_cv_issue_id,
                verified=entry.embedded_verified,
            ),
        )
        for entry in listing.entries
    ]


@router.post("/manual-import", status_code=201, response_model=CommandResource)
async def execute_manual_import_endpoint(
    body: ManualImportRequest, request: Request
) -> CommandResource:
    """Validate the corrected mappings and enqueue the manual-import command."""
    db = request.app.state.db
    service = request.app.state.commands
    if not body.files:
        raise ApiError(400, "no files supplied for manual import", field="files")

    roots = await execute_roots(db)
    payload_files: list[dict[str, object]] = []
    for spec in body.files:
        if spec.downloadId:
            # A download-scoped pick is confined by the command to the download's
            # own gathered files (only a path the download actually produced is
            # imported), so it is not root-confined here — the path is the mapped
            # local path the listing returned, which may sit outside a library
            # root (a download staging dir). Threaded through with its download id.
            path = spec.path
        else:
            confined = confine_under_roots(spec.path, roots)
            if confined is None:
                raise ApiError(
                    400,
                    f"path is not under a managed root or does not exist: {spec.path}",
                    field="files",
                )
            path = confined
        payload_files.append(
            {
                "path": path,
                "series_id": spec.seriesId,
                "issue_id": spec.issueId,
                "format": spec.format,
                "download_id": spec.downloadId,
            }
        )

    try:
        record = await service.enqueue("manual-import", {"files": payload_files})
    except CommandValidationError as exc:
        raise ApiError(400, str(exc), field="files") from exc
    return CommandResource.from_record(record)
