"""Read-only library-configuration lists for the add-series flow.

Two small GET collections the add-series screen (FRG-UI-005) reads to populate
its Root Folder and Format Profile pickers, rather than making the user type
raw ids:

- ``GET /api/v1/rootfolder`` — configured library root folders with free space
  when it can be read cheaply (FRG-SER-008).
- ``GET /api/v1/formatprofile`` — the seeded/managed format profiles
  (FRG-QUAL-001; the entity these list, served read-only for the add flow).

Both list GETs are plain arrays (no paging envelope): the sets are tiny and
unbounded growth is not a concern here. Root-folder *management*
(registration + removal, FRG-SER-008) also lives here now: without a create
surface a fresh install had no way to register a root folder — a first-run
blocker for series add, downloading, and library import. Format-profile
management remains a separate concern (out of scope for this change).
"""

from __future__ import annotations

import os
import shutil

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from foragerr.api.errors import ApiError
from foragerr.library import repo
from foragerr.quality.models import FormatProfileRow, decode_formats

router = APIRouter(tags=["config"])


class RootFolderResource(BaseModel):
    """A configured library root folder (FRG-SER-008).

    ``free_space`` is the filesystem's free bytes when it can be read cheaply
    (a single ``statvfs``); ``None`` when the path is missing or unreadable —
    a stat failure never fails the list."""

    id: int
    path: str
    free_space: int | None


class RootFolderCreate(BaseModel):
    """Request body for ``POST /api/v1/rootfolder`` (FRG-SER-008)."""

    path: str


class FormatProfileResource(BaseModel):
    """A format profile: an ordered format ladder plus a cutoff (FRG-QUAL-001)."""

    id: int
    name: str
    formats: list[str]
    cutoff: str


@router.get("/rootfolder", response_model=list[RootFolderResource])
async def list_root_folders_endpoint(request: Request) -> list[RootFolderResource]:
    """List configured root folders with free space where cheap (FRG-SER-008)."""
    db = request.app.state.db
    async with db.read_session() as session:
        rows = await repo.list_root_folders(session)
    return [
        RootFolderResource(
            id=row.id, path=row.path, free_space=await _free_space(row.path)
        )
        for row in rows
    ]


@router.post("/rootfolder", status_code=201, response_model=RootFolderResource)
async def create_root_folder_endpoint(
    body: RootFolderCreate, request: Request
) -> RootFolderResource:
    """Register a new library root folder (FRG-SER-008).

    Validates up front — the path must be absolute, an existing directory, and
    writable, and must neither duplicate nor nest with (under or containing) an
    existing root — and rejects any failure with a field-precise 400 naming the
    exact problem against ``path``. On success the row is persisted and returned
    with free space (the same resource the list serves)."""
    db = request.app.state.db
    async with db.write_session() as session:
        existing = await repo.list_root_folders(session)
        await run_in_threadpool(_validate_new_root, body.path, existing)
        row = await repo.create_root_folder(session, body.path)
        rid, path = row.id, row.path
    return RootFolderResource(id=rid, path=path, free_space=await _free_space(path))


@router.delete("/rootfolder/{root_folder_id}", status_code=204)
async def delete_root_folder_endpoint(root_folder_id: int, request: Request) -> None:
    """Remove a root folder (FRG-SER-008), files on disk untouched.

    404 when the id is unknown; 409 (naming the count) while any series still
    references it — deleting it would dangle those series' stored paths."""
    db = request.app.state.db
    async with db.write_session() as session:
        row = await repo.get_root_folder(session, root_folder_id)
        if row is None:
            raise ApiError(404, f"root folder {root_folder_id} not found")
        referencing = await repo.count_series_for_root(session, root_folder_id)
        if referencing:
            raise ApiError(
                409,
                f"root folder {root_folder_id} is still used by {referencing} "
                f"series — remove or relocate them first",
            )
        await repo.delete_root_folder(session, root_folder_id)
    return None


def _validate_new_root(path: str, existing: list) -> None:
    """Reject a bad root-folder registration with a field-precise
    :class:`ApiError` (400, ``field="path"``) naming the exact problem.

    Runs the blocking ``os.path`` stats in the thread pool (a wedged network
    mount must not freeze the loop). ``existing`` are the already-registered
    :class:`RootFolderRow`s to compare against for duplicate/nesting."""
    if not os.path.isabs(path):
        _reject(f"path {path!r} must be absolute")
    if not os.path.isdir(path):
        _reject(f"path {path!r} is not an existing directory")
    if not os.access(path, os.W_OK):
        _reject(f"path {path!r} is not writable")

    candidate = os.path.realpath(path)
    for root in existing:
        root_real = os.path.realpath(root.path)
        if candidate == root_real:
            _reject(f"path {path!r} is already registered as a root folder")
        if _is_within(root_real, candidate):
            _reject(f"path {path!r} is inside an existing root folder ({root.path})")
        if _is_within(candidate, root_real):
            _reject(f"path {path!r} contains an existing root folder ({root.path})")


def _is_within(ancestor: str, candidate: str) -> bool:
    """True if ``candidate`` sits at or beneath ``ancestor`` (segment-aware)."""
    if candidate == ancestor:
        return True
    try:
        return os.path.commonpath([ancestor, candidate]) == ancestor
    except ValueError:  # different drives / mixed absolute+relative
        return False


def _reject(message: str) -> None:
    raise ApiError(400, message, field="path")


@router.get("/formatprofile", response_model=list[FormatProfileResource])
async def list_format_profiles_endpoint(
    request: Request,
) -> list[FormatProfileResource]:
    """List every format profile, ordered by id (FRG-QUAL-001).

    Read-only: serves the add-series picker (FRG-UI-005). The seeded default
    (id 1) is always present (FRG-QUAL-002)."""
    db = request.app.state.db
    async with db.read_session() as session:
        rows = (
            (await session.execute(select(FormatProfileRow).order_by(FormatProfileRow.id)))
            .scalars()
            .all()
        )
    return [
        FormatProfileResource(
            id=row.id,
            name=row.name,
            formats=decode_formats(row.formats),
            cutoff=row.cutoff,
        )
        for row in rows
    ]


async def _free_space(path: str) -> int | None:
    """Free bytes on the filesystem holding ``path``, or ``None`` if it cannot
    be stat'd (missing mount, permission). Never raises — a stat failure must
    not fail the whole list.

    The ``disk_usage`` syscall is a BLOCKING stat that a hung network mount can
    stall on indefinitely, so it runs in the thread pool: one wedged root folder
    must never freeze the event loop and every other request with it."""
    try:
        usage = await run_in_threadpool(shutil.disk_usage, path)
    except OSError:
        return None
    return usage.free
