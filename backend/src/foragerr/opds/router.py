"""OPDS 1.2 catalog routes (FRG-OPDS-001, 002, 003, 005, 006).

Per-feed routes — a deliberate divergence from Mylar's single ``?cmd=``
dispatch endpoint::

    {base}                        root navigation feed  (shelves)
    {base}/series                 All Series navigation feed (paginated)
    {base}/series/{series_id}     one series' acquisition feed (paginated)
    {base}/file/{issue_file_id}   whole-file download

Security posture (this listener serves UNAUTHENTICATED content on the
Tailscale-only deployment, so every request value is treated as hostile):

- No route accepts a filesystem path, filename, or any string that becomes a
  path. Downloads are addressed by the integer ``issue_files.id`` only; the
  server resolves that id to a stored path and confirms the resolved path
  sits under a registered root folder before serving (FRG-OPDS-003). The
  Mylar ``?cmd=deliverFile&file=/etc/passwd`` traversal is therefore
  unrepresentable — there is no parameter to carry the path.
- Every query is an ORM ``select`` with bound parameters; no SQL text is
  built from request input (FRG-OPDS-004).
- Feed rendering reads DB rows only and never opens an archive
  (FRG-OPDS-002); the escaping Atom builder neutralizes injected markup.
"""

from __future__ import annotations

import datetime as dt
import math

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, select

from foragerr.api.errors import ApiError
from foragerr.db.base import utcnow
from foragerr.library import repo
from foragerr.library.models import IssueFileRow, IssueRow, SeriesRow

from foragerr.security.paths import PathConfinementError, validate_under_root
from foragerr.opds.atom import (
    ACQ_KIND,
    NAV_KIND,
    REL_ACQUISITION,
    REL_IMAGE,
    REL_START,
    REL_SUBSECTION,
    REL_THUMBNAIL,
    Entry,
    Feed,
    Link,
    render_feed,
)
from foragerr.opds.mime import media_type_for

CATALOG_TITLE = "foragerr"
ALL_SERIES_TITLE = "All Series"


def _feed_response(feed: Feed, kind: str) -> Response:
    """Serialize ``feed`` and return it with the OPDS feed content type."""
    return Response(content=render_feed(feed), media_type=kind)


def _cover_url(series_id: int) -> str:
    """Local cover-cache endpoint (FRG-META-013) — never a remote CDN URL."""
    return f"/api/v1/series/{series_id}/cover"


def _effective_page_size(count: int | None, settings) -> int:
    """Clamp the requested page size to the configured per-page cap
    (FRG-OPDS-006). ``None`` means the client did not ask — use the default."""
    size = settings.opds_page_size if count is None else count
    return max(1, min(size, settings.opds_page_size_cap))


def _pagination_links(feed_path: str, kind: str, page: int, page_size: int, total: int) -> tuple[list[Link], int]:
    """Atom next/previous/first/last links, every one pointing back at
    ``feed_path`` (the same feed it paginates — the Mylar wrong-``cmd`` bug
    class). Returns the link list and the last page number."""
    last_page = max(1, math.ceil(total / page_size)) if total else 1

    def url(p: int) -> str:
        return f"{feed_path}?page={p}&count={page_size}"

    links = [
        Link(href=url(1), rel="first", type=kind),
        Link(href=url(last_page), rel="last", type=kind),
    ]
    if page > 1:
        links.append(Link(href=url(page - 1), rel="previous", type=kind))
    if page < last_page:
        links.append(Link(href=url(page + 1), rel="next", type=kind))
    return links, last_page


def build_opds_router(base_path: str) -> APIRouter:
    """Build the OPDS router whose in-feed links are relative to ``base_path``
    (the configured mount prefix)."""
    router = APIRouter(tags=["opds"])

    series_shelf_url = f"{base_path}/series"

    def start_link() -> Link:
        return Link(href=base_path, rel=REL_START, type=NAV_KIND)

    @router.get("")
    async def root_feed(request: Request) -> Response:
        """Root navigation feed: links to shelves that have content
        (FRG-OPDS-001). M1 shelf set = All Series only, shown only when the
        library holds at least one series."""
        db = request.app.state.db
        async with db.read_session() as session:
            series_count = await session.scalar(
                select(func.count()).select_from(SeriesRow)
            )
        entries: list[Entry] = []
        if series_count:
            entries.append(
                Entry(
                    id=series_shelf_url,
                    title=ALL_SERIES_TITLE,
                    updated=utcnow(),
                    # Browse feed -> navigation kind (distinct from the
                    # acquisition kind carried by per-series links).
                    links=(Link(href=series_shelf_url, rel=REL_SUBSECTION, type=NAV_KIND),),
                )
            )
        feed = Feed(
            id=base_path,
            title=CATALOG_TITLE,
            updated=utcnow(),
            self_url=base_path,
            entries=tuple(entries),
        )
        return _feed_response(feed, NAV_KIND)

    @router.get("/series")
    async def series_shelf(
        request: Request,
        page: int = Query(1, ge=1),
        count: int | None = Query(None, ge=1),
    ) -> Response:
        """All Series navigation feed (FRG-OPDS-001, 006): one entry per
        series, each linking to that series' acquisition feed (acquisition
        kind). Paginated."""
        settings = request.app.state.settings
        page_size = _effective_page_size(count, settings)
        db = request.app.state.db
        async with db.read_session() as session:
            total = await session.scalar(select(func.count()).select_from(SeriesRow))
            total = total or 0
            rows = (
                (
                    await session.execute(
                        select(SeriesRow)
                        .order_by(SeriesRow.sort_title, SeriesRow.id)
                        .offset((page - 1) * page_size)
                        .limit(page_size)
                    )
                )
                .scalars()
                .all()
            )

        entries = tuple(
            Entry(
                id=f"{base_path}/series/{row.id}",
                title=row.title,
                updated=row.refreshed_at or row.added_at,
                links=(
                    Link(
                        href=f"{base_path}/series/{row.id}",
                        rel=REL_SUBSECTION,
                        # This link resolves to a feed of downloadable issues
                        # -> acquisition kind.
                        type=ACQ_KIND,
                    ),
                ),
            )
            for row in rows
        )

        nav_links, _ = _pagination_links(series_shelf_url, NAV_KIND, page, page_size, total)
        feed = Feed(
            id=series_shelf_url,
            title=ALL_SERIES_TITLE,
            updated=utcnow(),
            self_url=f"{series_shelf_url}?page={page}&count={page_size}",
            links=[start_link(), *nav_links],
            entries=entries,
            total_results=total,
            items_per_page=page_size,
            start_index=(page - 1) * page_size + 1,
        )
        return _feed_response(feed, NAV_KIND)

    @router.get("/series/{series_id}")
    async def series_acquisition_feed(
        series_id: int,
        request: Request,
        page: int = Query(1, ge=1),
        count: int | None = Query(None, ge=1),
    ) -> Response:
        """A series' acquisition feed (FRG-OPDS-002, 005, 006): one entry per
        downloadable issue-file, rendered entirely from DB fields — no archive
        is opened. Each entry carries an id-only acquisition link plus
        cover/thumbnail links into the local cover cache."""
        settings = request.app.state.settings
        page_size = _effective_page_size(count, settings)
        feed_path = f"{base_path}/series/{series_id}"
        db = request.app.state.db
        async with db.read_session() as session:
            series = await repo.get_series(session, series_id)
            if series is None:
                raise ApiError(404, f"no series {series_id}")

            base_query = (
                select(IssueFileRow, IssueRow)
                .join(IssueRow, IssueRow.id == IssueFileRow.issue_id)
                .where(IssueRow.series_id == series_id)
            )
            total = await session.scalar(
                select(func.count()).select_from(base_query.subquery())
            )
            total = total or 0
            result = await session.execute(
                base_query.order_by(IssueRow.ordering_key, IssueFileRow.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            pairs = result.all()

        cover = _cover_url(series_id)
        entries = tuple(
            _issue_file_entry(base_path, series, issue_file, issue, cover)
            for issue_file, issue in pairs
        )

        nav_links, _ = _pagination_links(feed_path, ACQ_KIND, page, page_size, total)
        feed = Feed(
            id=feed_path,
            title=series.title,
            updated=utcnow(),
            self_url=f"{feed_path}?page={page}&count={page_size}",
            links=[start_link(), *nav_links],
            entries=entries,
            total_results=total,
            items_per_page=page_size,
            start_index=(page - 1) * page_size + 1,
        )
        return _feed_response(feed, ACQ_KIND)

    @router.get("/file/{issue_file_id}")
    async def download_file(issue_file_id: int, request: Request) -> FileResponse:
        """Whole-file download by issue-file id ONLY (FRG-OPDS-003, 005).

        The id is resolved to a stored path, the path is confined to a
        registered root folder, then the original bytes are streamed with the
        format-specific comic media type and a Content-Disposition filename.
        No archive is opened or parsed. Unknown or out-of-root id -> 404."""
        db = request.app.state.db
        async with db.read_session() as session:
            row = await session.get(IssueFileRow, issue_file_id)
            if row is None:
                raise ApiError(404, f"no issue-file {issue_file_id}")
            stored_path = row.path
            roots = [rf.path for rf in await repo.list_root_folders(session)]

        try:
            resolved = validate_under_root(stored_path, roots)
        except PathConfinementError as exc:
            # A row whose path escaped every managed root is treated as
            # "not found" — the client cannot distinguish it from a bad id
            # and no bytes outside the library are ever served.
            raise ApiError(404, f"no issue-file {issue_file_id}") from exc

        if not resolved.is_file():
            raise ApiError(404, f"no issue-file {issue_file_id}")

        return FileResponse(
            resolved,
            media_type=media_type_for(resolved),
            filename=resolved.name,
        )

    return router


def _issue_file_entry(
    base_path: str,
    series: SeriesRow,
    issue_file: IssueFileRow,
    issue: IssueRow,
    cover_url: str,
) -> Entry:
    """One acquisition entry for a downloadable issue-file, built from DB
    fields only (FRG-OPDS-002)."""
    number = issue.issue_number or "?"
    title = issue.title or f"{series.title} #{number}"
    # updated: file-added timestamp, falling back to the issue's release date.
    updated: dt.datetime = issue_file.added_at
    if updated is None:  # defensive; added_at is NOT NULL in the schema
        release = issue.store_date or issue.cover_date
        updated = (
            dt.datetime.combine(release, dt.time(), tzinfo=dt.timezone.utc)
            if release
            else utcnow()
        )
    return Entry(
        id=f"{base_path}/file/{issue_file.id}",
        title=title,
        updated=updated,
        links=(
            Link(
                href=f"{base_path}/file/{issue_file.id}",
                rel=REL_ACQUISITION,
                type=media_type_for(issue_file.path),
            ),
            Link(href=cover_url, rel=REL_IMAGE, type="image/jpeg"),
            Link(href=cover_url, rel=REL_THUMBNAIL, type="image/jpeg"),
        ),
    )
