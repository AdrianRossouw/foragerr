"""OPDS 1.2 catalog routes (FRG-OPDS-001, 002, 003, 005, 006, 007, 013).

Per-feed routes — a deliberate divergence from Mylar's single ``?cmd=``
dispatch endpoint::

    {base}                        root navigation feed  (shelves + search link)
    {base}/series                 All Series navigation feed (paginated)
    {base}/series/{series_id}     one series' acquisition feed (paginated)
    {base}/recent                 Recent Additions acquisition feed (paginated)
    {base}/opensearch.xml         OpenSearch description document
    {base}/search?q=              series search feed (paginated)
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
  built from request input (FRG-OPDS-004). The search term (the one free-text
  request input, FRG-OPDS-007) is length-capped, folded through the shared
  ``matching_key`` normalization, and only ever compared — as a bound LIKE
  parameter with autoescaped wildcards, or by Python substring containment —
  never interpolated anywhere.
- Feed rendering reads DB rows only and never opens an archive
  (FRG-OPDS-002); the escaping Atom builder neutralizes injected markup.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import math
import os
from pathlib import Path
from urllib.parse import quote_plus, urljoin

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, select

logger = logging.getLogger("foragerr.opds")

from foragerr.api.errors import ApiError
from foragerr.db.base import utcnow
from foragerr.library import repo
from foragerr.library.flows import decode_aliases
from foragerr.library.models import IssueFileRow, IssueRow, SeriesRow
from foragerr.parser.normalize import matching_key

from foragerr.security.archives import (
    ArchiveMemberError,
    list_image_members,
    read_image_member,
)
from foragerr.security.images import ImageRenderError, render_page
from foragerr.security.paths import PathConfinementError, validate_under_root
from foragerr.opds.atom import (
    ACQ_KIND,
    NAV_KIND,
    OPENSEARCH_DESC_KIND,
    REL_ACQUISITION,
    REL_IMAGE,
    REL_PSE_STREAM,
    REL_SEARCH,
    REL_START,
    REL_SUBSECTION,
    REL_THUMBNAIL,
    Entry,
    Feed,
    Link,
    render_feed,
    render_opensearch_description,
)
from foragerr.opds.mime import media_type_for

CATALOG_TITLE = "foragerr"
ALL_SERIES_TITLE = "All Series"
RECENT_TITLE = "Recent Additions"
SEARCH_TITLE = "Search"

#: Upper bound on the hostile free-text search term (FRG-OPDS-007). Anything
#: beyond it is TRIMMED (never an error): the spec requires oversized input to
#: be bounded while the response stays a normal, possibly empty, feed.
MAX_SEARCH_QUERY_LEN = 256

#: Bound on how many alias-bearing series the search loads for the Python-side
#: fold+contain pass (FRG-OPDS-007). Title matches use ``matching_key`` (already
#: the folded form) as an exact SQL superset and are NOT capped; only aliases —
#: stored as raw user strings whose folded form cannot be expressed in SQL —
#: are candidate-scanned, so this caps that scan alone. A single-user library
#: stays far under it; if it is ever hit a WARNING flags that alias matches
#: beyond the cap could be missed (correctness inside the cap is preserved —
#: matches are never silently dropped from the fetched candidates).
OPDS_ALIAS_SCAN_CAP = 2000


def _feed_response(feed: Feed, kind: str) -> Response:
    """Serialize ``feed`` and return it with the OPDS feed content type."""
    return Response(content=render_feed(feed), media_type=kind)


async def _count_and_page(session, stmt, *, order_by, page: int, page_size: int):
    """Shared count + offset/limit slice for both OPDS feed routes.

    ``foragerr.api.paging.paginate`` does not fit here: it returns the JSON
    paging envelope, sorts through a per-endpoint whitelist, and ``.scalars()``
    the rows — whereas the OPDS acquisition feed pages a two-entity join and
    needs the full ``Result``. This keeps the count/offset/limit logic in ONE
    place; the caller shapes the returned ``Result`` (``.scalars()`` or
    ``.all()``). Returns ``(total, result)``; ``total`` is never ``None``."""
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await session.execute(
        stmt.order_by(*order_by).offset((page - 1) * page_size).limit(page_size)
    )
    return (total or 0), result


def _cover_url(base_path: str, series_id: int) -> str:
    """Cached series-cover endpoint on the OPDS realm (FRG-META-013) — never a
    remote CDN URL, and never the ``/api`` route: an OPDS reader authenticates
    with OPDS Basic, which the API perimeter rejects, so a feed advertising an
    ``/api`` image link leaves every cover unloadable (a reader 401s following
    it). Kept under ``base_path`` so it rides the same Basic realm as the feed."""
    return f"{base_path}/series-cover/{series_id}"


#: Local first-page cover render widths (FRG-OPDS-011). The full cover is
#: additionally bounded by ``opds_pse_max_width``; the thumbnail is smaller for
#: list/grid rendering. Never upscaled (``render_page`` only ever shrinks).
_COVER_MAX_WIDTH = 640
_COVER_THUMB_WIDTH = 256

#: Advertised media type of the OPDS-PSE stream + local-cover links. Photographic
#: comic pages/covers re-encode to JPEG (``render_page`` returns PNG only for the
#: rare alpha-bearing source; the local-cover path forces JPEG so its cache and
#: this content type are always truthful).
_PSE_IMAGE_TYPE = "image/jpeg"

#: Maximum concurrent PSE image renders (FRG-OPDS-012). A single in-cap decode can
#: allocate ~256 MB (a 64-megapixel RGBA), and ``render_page`` runs on an offload
#: thread that a per-request timeout can CANCEL-the-await on but NOT actually kill
#: — the thread runs to completion. Without a bound, a flood of ``/page``+``/cover``
#: requests at large in-cap images would pile those un-killable threads (and their
#: decode memory) up without limit and exhaust the default thread pool. This
#: semaphore is therefore what bounds aggregate render memory/threads: its permit
#: is held until the thread genuinely FINISHES (released in a done-callback, not
#: when a timed-out await is cancelled), so at most this many decodes are ever live.
_RENDER_CONCURRENCY = 3
_render_semaphore = asyncio.Semaphore(_RENDER_CONCURRENCY)


async def _resolve_confined_file(session, issue_file_id: int) -> tuple[IssueFileRow, Path]:
    """Resolve an issue-file id to its row and confinement-checked on-disk path.

    The id-only, root-confined resolution the whole OPDS file surface shares
    (FRG-OPDS-003), identical to :func:`download_file`: ``session.get`` the row,
    confirm its stored path resolves under a registered root
    (:func:`validate_under_root`), and confirm it is a regular file. An unknown
    id, an out-of-root path, or a missing file all degrade to the SAME 404 a
    client cannot tell apart — no path outside a managed root is ever probed or
    served, and no client-supplied string ever reaches the filesystem.
    """
    row = await session.get(IssueFileRow, issue_file_id)
    if row is None:
        raise ApiError(404, f"no issue-file {issue_file_id}")
    roots = [rf.path for rf in await repo.list_root_folders(session)]
    try:
        resolved = validate_under_root(row.path, roots)
    except PathConfinementError as exc:
        raise ApiError(404, f"no issue-file {issue_file_id}") from exc
    if not resolved.is_file():
        raise ApiError(404, f"no issue-file {issue_file_id}")
    return row, resolved


def _effective_page_size(count: int | None, settings) -> int:
    """Clamp the requested page size to the configured per-page cap
    (FRG-OPDS-006). ``None`` means the client did not ask — use the default."""
    size = settings.opds_page_size if count is None else count
    return max(1, min(size, settings.opds_page_size_cap))


def _pagination_links(
    feed_path: str,
    kind: str,
    page: int,
    page_size: int,
    total: int,
    *,
    extra_query: str = "",
) -> tuple[list[Link], int]:
    """Atom next/previous/first/last links, every one pointing back at
    ``feed_path`` (the same feed it paginates — the Mylar wrong-``cmd`` bug
    class). ``extra_query`` carries feed-specific parameters (the search
    feed's already-encoded ``q=...&``) so pagination never drops them.
    Returns the link list and the last page number."""
    last_page = max(1, math.ceil(total / page_size)) if total else 1

    def url(p: int) -> str:
        return f"{feed_path}?{extra_query}page={p}&count={page_size}"

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
    recent_url = f"{base_path}/recent"
    search_url = f"{base_path}/search"
    descriptor_url = f"{base_path}/opensearch.xml"

    def start_link() -> Link:
        return Link(href=base_path, rel=REL_START, type=NAV_KIND)

    def search_link() -> Link:
        """The advertised OpenSearch descriptor link (FRG-OPDS-007 option a):
        advertised because the descriptor AND the search feed are implemented —
        never a dangling promise."""
        return Link(href=descriptor_url, rel=REL_SEARCH, type=OPENSEARCH_DESC_KIND)

    @router.get("")
    async def root_feed(request: Request) -> Response:
        """Root navigation feed: links to shelves that have content
        (FRG-OPDS-001, FRG-OPDS-013) plus the OpenSearch link (FRG-OPDS-007).
        Shelf set = All Series (shown only when the library holds at least one
        series) and Recent Additions (shown only when at least one issue file
        exists — the same non-empty convention)."""
        db = request.app.state.db
        async with db.read_session() as session:
            series_stmt = select(func.count()).select_from(SeriesRow)
            if request.app.state.settings.opds_hide_fileless_series:
                # Advertise "All Series" only when the shelf would actually
                # list something: the same file-bearing predicate the shelf
                # applies (FRG-OPDS-018), or a filtered-empty shelf gets a
                # nav entry that opens to nothing.
                series_stmt = series_stmt.where(
                    select(IssueFileRow.id)
                    .join(IssueRow, IssueRow.id == IssueFileRow.issue_id)
                    .where(
                        IssueRow.series_id == SeriesRow.id,
                        IssueFileRow.edition_issue_id.is_(None),
                    )
                    .exists()
                )
            series_count = await session.scalar(series_stmt)
            file_count = await session.scalar(
                select(func.count()).select_from(IssueFileRow)
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
        if file_count:
            entries.append(
                Entry(
                    id=recent_url,
                    title=RECENT_TITLE,
                    updated=utcnow(),
                    # Resolves to a feed of downloadable issues -> acquisition.
                    links=(Link(href=recent_url, rel=REL_SUBSECTION, type=ACQ_KIND),),
                )
            )
        feed = Feed(
            id=base_path,
            title=CATALOG_TITLE,
            updated=utcnow(),
            self_url=base_path,
            links=(search_link(),),
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
        kind). Paginated.

        File-less series are omitted by default (FRG-OPDS-018,
        ``opds_hide_fileless_series``) so a reader browses only shelves with
        something to read: the SQL filter keeps only series with at least one
        downloadable file (an ``issue_files`` row that is not an owned-via-
        edition provenance marker — the same rows the acquisition feed serves).
        The opt-out lists every series, empty shelves included."""
        settings = request.app.state.settings
        page_size = _effective_page_size(count, settings)
        stmt = select(SeriesRow)
        if settings.opds_hide_fileless_series:
            has_file = (
                select(IssueFileRow.id)
                .join(IssueRow, IssueRow.id == IssueFileRow.issue_id)
                .where(
                    IssueRow.series_id == SeriesRow.id,
                    IssueFileRow.edition_issue_id.is_(None),
                )
                .exists()
            )
            stmt = stmt.where(has_file)
        db = request.app.state.db
        async with db.read_session() as session:
            total, result = await _count_and_page(
                session,
                stmt,
                order_by=(SeriesRow.sort_title, SeriesRow.id),
                page=page,
                page_size=page_size,
            )
            rows = result.scalars().all()

        entries = tuple(_series_nav_entry(base_path, row) for row in rows)

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
                # Owned-via-edition rows (FRG-SRC-007) are size-0 provenance
                # markers pointing at a shared collected file, not distinct
                # downloadable copies; excluding them keeps the acquisition feed
                # to real single/collected files (no duplicate entries).
                .where(IssueFileRow.edition_issue_id.is_(None))
            )
            total, result = await _count_and_page(
                session,
                base_query,
                order_by=(IssueRow.ordering_key, IssueFileRow.id),
                page=page,
                page_size=page_size,
            )
            pairs = result.all()

        cover = _cover_url(base_path, series_id)
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

    @router.get("/recent")
    async def recent_feed(
        request: Request,
        page: int = Query(1, ge=1),
        count: int | None = Query(None, ge=1),
    ) -> Response:
        """Recent Additions acquisition feed (FRG-OPDS-013): every issue file
        in the library ordered newest-first by IMPORT time (``added_at``,
        never release date), paginated per FRG-OPDS-006 — the pagination is
        what bounds the shelf; there is no separate window config. Entries are
        the same full acquisition entries the series shelf serves."""
        settings = request.app.state.settings
        page_size = _effective_page_size(count, settings)
        db = request.app.state.db
        async with db.read_session() as session:
            base_query = (
                select(IssueFileRow, IssueRow, SeriesRow)
                .join(IssueRow, IssueRow.id == IssueFileRow.issue_id)
                .join(SeriesRow, SeriesRow.id == IssueRow.series_id)
                # Exclude owned-via-edition provenance rows (FRG-SRC-007) — a
                # single collected file must not appear once per filled single.
                .where(IssueFileRow.edition_issue_id.is_(None))
            )
            total, result = await _count_and_page(
                session,
                base_query,
                order_by=(IssueFileRow.added_at.desc(), IssueFileRow.id.desc()),
                page=page,
                page_size=page_size,
            )
            triples = result.all()

        entries = tuple(
            _issue_file_entry(base_path, series, issue_file, issue, _cover_url(base_path, series.id))
            for issue_file, issue, series in triples
        )

        nav_links, _ = _pagination_links(recent_url, ACQ_KIND, page, page_size, total)
        feed = Feed(
            id=recent_url,
            title=RECENT_TITLE,
            updated=utcnow(),
            self_url=f"{recent_url}?page={page}&count={page_size}",
            links=[start_link(), *nav_links],
            entries=entries,
            total_results=total,
            items_per_page=page_size,
            start_index=(page - 1) * page_size + 1,
        )
        return _feed_response(feed, ACQ_KIND)

    @router.get("/opensearch.xml")
    async def opensearch_description(request: Request) -> Response:
        """The OpenSearch description document the root feed's ``rel="search"``
        link advertises (FRG-OPDS-007 option a). The template MUST be an
        absolute URL: a root-relative one (``/opds/search?...``) breaks behind a
        path-prefix reverse proxy (the reader resolves it against the wrong
        base) and some readers reject it outright. It is built from the incoming
        request's base URL — which respects the proxy ``root_path`` /
        forwarded-prefix the ASGI stack set, exactly as ``request.base_url``
        does — joined with this catalog's own ``{base_path}/search`` mount, so
        the advertised template points where the reader actually reached us.
        The literal ``{searchTerms}`` placeholder is preserved for the reader to
        substitute. (In-feed links stay relative — a browsing reader resolves
        them against the feed URL it fetched.)"""
        # base_url ends with "/" and already carries any proxy root_path;
        # search_url is the app-relative mount ("/opds/search"), so strip its
        # leading slash for a correct urljoin against that base.
        template = urljoin(
            str(request.base_url), f"{search_url.lstrip('/')}?q={{searchTerms}}"
        )
        document = render_opensearch_description(
            short_name=CATALOG_TITLE,
            description="Search series in the foragerr comic catalog",
            template=template,
            results_type=NAV_KIND,
        )
        return Response(content=document, media_type=OPENSEARCH_DESC_KIND)

    @router.get("/search")
    async def search_feed(
        request: Request,
        q: str = Query(""),
        page: int = Query(1, ge=1),
        count: int | None = Query(None, ge=1),
    ) -> Response:
        """Series search feed (FRG-OPDS-007): case-folded containment match of
        the query against every series title AND its aliases, returning
        navigation entries into the matching series' acquisition feeds.

        The term is the one hostile free-text input on this unauthenticated
        listener, so it is bounded and inert by construction: trimmed to
        ``MAX_SEARCH_QUERY_LEN``, folded through the shared ``matching_key``
        normalization (FRG-IMP-005 — resilient to case/punctuation/unicode
        variants), compared via a bound autoescaped LIKE parameter plus a
        Python containment pass over the (folded) alias lists, and reflected
        nowhere except URL-encoded into this feed's own pagination links,
        which the escaping builder quotes. No match — or an empty/fold-empty
        term — yields an empty but valid feed, never an error.

        Fetch is bounded WITHOUT loading every aliased series (the pre-fix cost):
        title matches use ``matching_key`` (already the folded form), so a folded
        substring is an EXACT SQL superset — those rows are fetched unbounded and
        are guaranteed matches. Only alias-bearing series (whose folded form is
        not expressible in SQL) are candidate-scanned, and that scan is capped at
        ``OPDS_ALIAS_SCAN_CAP`` with a WARNING if the cap is reached; matches are
        never silently dropped from the fetched candidates."""
        settings = request.app.state.settings
        page_size = _effective_page_size(count, settings)
        term = q[:MAX_SEARCH_QUERY_LEN]
        folded = matching_key(term)

        matched: dict[int, SeriesRow] = {}
        if folded:
            db = request.app.state.db
            async with db.read_session() as session:
                # 1. Title matches: `matching_key` IS the folded form, so a
                #    folded-substring LIKE (bound, autoescaped) is an exact
                #    superset — every returned row genuinely matches, no cap.
                title_rows = (
                    (
                        await session.execute(
                            select(SeriesRow)
                            .where(
                                SeriesRow.matching_key.contains(
                                    folded, autoescape=True
                                )
                            )
                            .order_by(SeriesRow.sort_title, SeriesRow.id)
                        )
                    )
                    .scalars()
                    .all()
                )
                for row in title_rows:
                    matched[row.id] = row

                # 2. Alias matches: a raw user string whose folded form cannot be
                #    expressed in SQL, so alias-bearing series are candidates
                #    filtered in Python. Bound the candidate fetch so a huge
                #    library cannot load every aliased series; order it so the
                #    cap is deterministic, and WARN (never silently truncate a
                #    match inside the fetched set) if the cap is reached.
                alias_candidates = (
                    (
                        await session.execute(
                            select(SeriesRow)
                            .where(SeriesRow.aliases.is_not(None))
                            .order_by(SeriesRow.sort_title, SeriesRow.id)
                            .limit(OPDS_ALIAS_SCAN_CAP + 1)
                        )
                    )
                    .scalars()
                    .all()
                )
                if len(alias_candidates) > OPDS_ALIAS_SCAN_CAP:
                    logger.warning(
                        "opds search: alias candidate scan hit the %d cap; alias "
                        "matches beyond it may be missed for this query",
                        OPDS_ALIAS_SCAN_CAP,
                    )
                    alias_candidates = alias_candidates[:OPDS_ALIAS_SCAN_CAP]
                for row in alias_candidates:
                    if row.id not in matched and _series_matches(row, folded):
                        matched[row.id] = row

        rows = sorted(matched.values(), key=lambda r: (r.sort_title, r.id))
        total = len(rows)
        start = (page - 1) * page_size
        entries = tuple(
            _series_nav_entry(base_path, row) for row in rows[start : start + page_size]
        )

        extra_query = f"q={quote_plus(term)}&"
        nav_links, _ = _pagination_links(
            search_url, NAV_KIND, page, page_size, total, extra_query=extra_query
        )
        feed = Feed(
            id=search_url,
            title=SEARCH_TITLE,
            updated=utcnow(),
            self_url=f"{search_url}?{extra_query}page={page}&count={page_size}",
            links=[start_link(), *nav_links],
            entries=entries,
            total_results=total,
            items_per_page=page_size,
            start_index=start + 1,
        )
        return _feed_response(feed, NAV_KIND)

    @router.get("/file/{issue_file_id}")
    async def download_file(issue_file_id: int, request: Request) -> FileResponse:
        """Whole-file download by issue-file id ONLY (FRG-OPDS-003, 005).

        The id is resolved to a stored path, the path is confined to a
        registered root folder, then the original bytes are streamed with the
        format-specific comic media type and a Content-Disposition filename.
        No archive is opened or parsed. Unknown or out-of-root id -> 404.

        A HEAD preflight (FRG-OPDS-017) resolves+stats the file exactly as GET
        but streams no bytes: ``FileResponse`` fills Content-Length from the
        stat and returns an empty body for the HEAD method — the whole file is
        never read."""
        db = request.app.state.db
        async with db.read_session() as session:
            # The id-only, root-confined resolution shared with the page/cover
            # surface — a bad, out-of-root, or missing id all degrade to 404.
            _row, resolved = await _resolve_confined_file(session, issue_file_id)

        return FileResponse(
            resolved,
            media_type=media_type_for(resolved),
            filename=resolved.name,
        )

    @router.get("/page/{issue_file_id}/{page}")
    async def stream_page(
        issue_file_id: int,
        page: int,
        request: Request,
        width: int | None = Query(None, ge=1),
    ) -> Response:
        """OPDS-PSE single-page stream (FRG-OPDS-008, FRG-OPDS-012).

        Resolves the archive by issue-file id ONLY (id-only, root-confined —
        :func:`_resolve_confined_file`), lists its ordered image members from the
        central directory (no decompression), reads the requested member under a
        declared-size cap, then decodes/downscales it under a pixel cap and a
        per-request wall-clock timeout on an offload thread — so untrusted archive
        bytes can neither exhaust memory nor wedge the event loop. An out-of-range
        or negative ``page``, a non-listable archive (CBR without ``rarfile``,
        corrupt/hostile), or an unknown/out-of-root id all return 404; a member
        that cannot be read or an image that cannot be rendered returns a bounded
        5xx; an over-budget decode returns 503. The optional ``width`` is clamped
        to ``opds_pse_max_width`` and the image is never upscaled."""
        settings = request.app.state.settings
        db = request.app.state.db

        # 1. Resolve id -> confined path in a short READ session (no archive I/O
        #    under the process-global writer lock, and none on the event loop).
        async with db.read_session() as session:
            row, resolved = await _resolve_confined_file(session, issue_file_id)
            cached_count = row.page_count

        # A HEAD preflight (FRG-OPDS-017) mirrors GET's status but MUST NOT do
        # the expensive member read/decode. Status parity still requires the
        # same existence checks GET performs (out-of-range page, no-image or
        # unlistable archive → 404), so validate via the cached page count when
        # present, else one bounded listing — never a member read or render.
        if request.method == "HEAD":
            # Trusting a present cached_count skips the listing; a stale count
            # could 200 a page GET would 404 — accepted (HEAD stays cheap, the
            # cache self-heals on the next GET's write-back below).
            if cached_count:
                if page < 0 or page >= cached_count:
                    raise ApiError(
                        404, f"page {page} out of range for issue-file {issue_file_id}"
                    )
            else:
                await _validate_archive_page(
                    resolved, page, settings, what=f"issue-file {issue_file_id}"
                )
            # Advertised PSE type: GET may return image/png for an alpha
            # source, but the feed link advertises jpeg — HEAD matches the
            # advertisement without paying for a decode.
            return Response(media_type=_PSE_IMAGE_TYPE)

        # 2. Read the requested page: lists the archive ONCE, off the event loop,
        #    outside any write session, and reads the member under the per-page cap.
        data, member_count = await _read_archive_page(
            resolved, page, settings, what=f"issue-file {issue_file_id}"
        )

        # 3. Lazy write-back (FRG-OPDS-009): persist the freshly-listed count when
        #    the row's stored value is NULL/stale. A SHORT write session wrapping
        #    ONLY the cheap DB update — never archive I/O under the writer lock,
        #    and never a re-list (we already have the count from step 2).
        if cached_count != member_count:
            async with db.write_session() as session:
                fresh = await session.get(IssueFileRow, issue_file_id)
                if fresh is not None and fresh.page_count != member_count:
                    fresh.page_count = member_count

        # 4. Decode/downscale off-loop under the pixel cap, wall-clock timeout AND
        #    the render-concurrency bound.
        out, content_type = await _render_bounded(
            settings,
            data,
            max_width=(
                min(width, settings.opds_pse_max_width) if width is not None else None
            ),
            what=f"page {page} of issue-file {issue_file_id}",
        )
        return Response(content=out, media_type=content_type)

    @router.get("/series-cover/{series_id}")
    async def series_cover(series_id: int, request: Request) -> Response:
        """The cached ComicVine series cover, served on the OPDS Basic realm
        (FRG-OPDS-019). The feed advertises THIS as an entry's image/thumbnail
        link when the series has a remote cover cached; it serves the identical
        bytes as the web-UI ``/api/v1/series/{id}/cover`` route but under OPDS
        auth, so a reader that authenticated with Basic can actually load it
        (the ``/api`` route rejects Basic — the bug this route fixes). Missing
        cover -> 404, exactly like the API route. ``series_id`` is an int, so
        the cache path is a fixed ``covers/<id>.jpg`` under the config dir with
        no request-controlled path component."""
        settings = request.app.state.settings
        cover_path = Path(settings.config_dir) / "covers" / f"{series_id}.jpg"
        if not cover_path.is_file():
            raise ApiError(404, f"no cached cover for series {series_id}")
        # HEAD parity (FRG-OPDS-017): FileResponse fills Content-Length from a
        # single stat and answers HEAD with headers + empty body.
        return FileResponse(cover_path, media_type=_PSE_IMAGE_TYPE)

    @router.get("/cover/{issue_file_id}")
    async def local_cover(issue_file_id: int, request: Request) -> Response:
        """Local first-page cover for a cover-less issue (FRG-OPDS-011).

        The fallback the acquisition entry points image/thumbnail links at when a
        series has NO remote ComicVine cover. The first archive page is extracted,
        downscaled (a smaller image for ``?thumbnail``) and cached under
        ``<config>/covers/pages/<id>[_thumb].jpg`` — a per-issue-file key space
        deliberately separate from the per-series ComicVine cache. A cached file
        that is at least as new as its source archive is served straight from
        disk; otherwise it is extracted/rendered under the same caps + timeout as
        the page stream, written atomically, then served. No external host is ever
        contacted."""
        settings = request.app.state.settings
        thumbnail = "thumbnail" in request.query_params

        # Resolve + confine FIRST — BEFORE consulting the cache — so a deleted or
        # moved-out-of-root id 404s even when a stale cover is still on disk (never
        # serve bytes for an id that no longer resolves under a managed root).
        db = request.app.state.db
        async with db.read_session() as session:
            _row, resolved = await _resolve_confined_file(session, issue_file_id)

        # A HEAD preflight (FRG-OPDS-017) mirrors GET's status but skips the
        # extract/render+cache. Parity requires GET's existence checks: a fresh
        # cached cover proves streamability outright; otherwise validate page 0
        # exists (cached count or one bounded listing) — no read, no render.
        if request.method == "HEAD":
            covers_dir = Path(settings.config_dir) / "covers" / "pages"
            head_cache = covers_dir / (
                f"{issue_file_id}{'_thumb' if thumbnail else ''}.jpg"
            )
            if not _cover_cache_is_fresh(head_cache, resolved):
                if not _row.page_count:
                    await _validate_archive_page(
                        resolved, 0, settings, what=f"issue-file {issue_file_id}"
                    )
            return Response(media_type=_PSE_IMAGE_TYPE)

        covers_dir = Path(settings.config_dir) / "covers" / "pages"
        cache_path = covers_dir / f"{issue_file_id}{'_thumb' if thumbnail else ''}.jpg"
        # Serve the cache only when it is at least as new as the source archive: a
        # changed source (newer mtime) invalidates the stale cover and regenerates.
        if _cover_cache_is_fresh(cache_path, resolved):
            return FileResponse(cache_path, media_type=_PSE_IMAGE_TYPE)

        data, _member_count = await _read_archive_page(
            resolved, 0, settings, what=f"issue-file {issue_file_id}"
        )

        # force_jpeg: the cover cache is always ``.jpg`` served as image/jpeg, so an
        # alpha first page is flattened to JPEG rather than mislabeled PNG bytes.
        out, _content_type = await _render_bounded(
            settings,
            data,
            max_width=(
                _COVER_THUMB_WIDTH
                if thumbnail
                else min(settings.opds_pse_max_width, _COVER_MAX_WIDTH)
            ),
            what=f"cover of issue-file {issue_file_id}",
            force_jpeg=True,
        )

        # Atomic cache publish: write a unique temp then rename over the target so
        # a concurrent reader never sees a half-written cover.
        covers_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = cache_path.with_name(f"{cache_path.name}.{os.getpid()}.{id(out)}.tmp")
        try:
            tmp_path.write_bytes(out)
            os.replace(tmp_path, cache_path)
        except OSError as exc:
            tmp_path.unlink(missing_ok=True)
            logger.warning("opds cover cache write failed (file=%s): %s", issue_file_id, exc)
            # The bytes are good even if caching failed — serve them directly.
            return Response(content=out, media_type=_PSE_IMAGE_TYPE)
        return FileResponse(cache_path, media_type=_PSE_IMAGE_TYPE)

    # HEAD parity (FRG-OPDS-017): reader apps and proxies preflight OPDS URLs
    # with HEAD, but FastAPI does not add HEAD to a GET route, so a bare HEAD
    # would 404/405 and never even reach the default-deny perimeter to receive
    # the Basic challenge. Register each GET handler under HEAD too, EXCLUDED
    # from the OpenAPI schema (``include_in_schema=False``) so the GET route
    # remains the single documented operation — no duplicate-operationId. The
    # feed handlers render as usual (cheap DB reads) and Starlette drops the body
    # for HEAD; the file handler answers from a stat via ``FileResponse``; the
    # page/cover handlers branch on ``request.method`` above to skip the archive
    # read/decode entirely. The app-root perimeter still guards these routes, so
    # an unauthenticated HEAD gets the identical 401 + Basic challenge as GET.
    for path, handler in (
        ("", root_feed),
        ("/series", series_shelf),
        ("/series/{series_id}", series_acquisition_feed),
        ("/recent", recent_feed),
        ("/opensearch.xml", opensearch_description),
        ("/search", search_feed),
        ("/file/{issue_file_id}", download_file),
        ("/page/{issue_file_id}/{page}", stream_page),
        ("/series-cover/{series_id}", series_cover),
        ("/cover/{issue_file_id}", local_cover),
    ):
        router.add_api_route(
            path, handler, methods=["HEAD"], include_in_schema=False
        )

    return router


def _cover_cache_is_fresh(cache_path: Path, source_path: Path) -> bool:
    """True when a cached cover exists AND is at least as new as its source
    archive (FRG-OPDS-011). A cheap ``stat`` mtime compare — no hash — so a
    source whose bytes changed (newer mtime) invalidates the stale cover and
    forces a regenerate. Any stat failure (missing cache, vanished source) is
    treated as "not fresh" so the caller falls through to a fresh render."""
    try:
        return cache_path.stat().st_mtime >= source_path.stat().st_mtime
    except OSError:
        return False


async def _validate_archive_page(
    resolved: Path, index: int, settings, *, what: str
) -> int:
    """The existence half of :func:`_read_archive_page` — one bounded listing
    (off the event loop) + bounds check, NO member read or decode. Gives HEAD
    the same 404 surface as GET (FRG-OPDS-017) at listing cost only. Returns
    the member count."""
    limits = settings.opds_pse_archive_limits()
    members = await asyncio.to_thread(list_image_members, resolved, limits)
    if not members:  # None (not listable) or [] (no image pages)
        raise ApiError(404, f"no streamable pages for {what}")
    if index < 0 or index >= len(members):
        raise ApiError(404, f"page {index} out of range for {what}")
    return len(members)


async def _read_archive_page(
    resolved: Path, index: int, settings, *, what: str
) -> tuple[bytes, int]:
    """List an archive's image members ONCE (off the event loop), bounds-check
    ``index``, and read that member under the per-page byte cap — the block the
    page-stream and local-cover endpoints share (FRG-OPDS-008/012).

    Returns ``(member_bytes, member_count)``. Raises ``ApiError(404)`` when the
    archive is not listable, has no image pages, or ``index`` is out of range;
    ``ApiError(502)`` (logged) when the member cannot be read. The listing uses
    ``opds_pse_archive_limits()`` (member-count cap; declared-size cap stays at
    the import default so listability matches import), while the read enforces the
    tight per-page ``opds_pse_max_page_bytes`` so a single oversized page is
    refused pre-decompression without failing the whole archive."""
    limits = settings.opds_pse_archive_limits()
    members = await asyncio.to_thread(list_image_members, resolved, limits)
    if not members:  # None (not listable) or [] (no image pages)
        raise ApiError(404, f"no streamable pages for {what}")
    if index < 0 or index >= len(members):
        raise ApiError(404, f"page {index} out of range for {what}")
    try:
        data = await asyncio.to_thread(
            read_image_member,
            resolved,
            members[index],
            max_bytes=settings.opds_pse_max_page_bytes,
        )
    except ArchiveMemberError as exc:
        logger.warning("opds page read refused (%s page=%d): %s", what, index, exc)
        raise ApiError(502, f"page {index} could not be read") from exc
    return data, len(members)


def _release_render_permit(task: asyncio.Future) -> None:
    """Release the render semaphore when the offload thread genuinely finishes.

    Bound as a done-callback rather than releasing on ``wait_for`` timeout: the
    thread cannot be killed, so holding the permit until true completion is what
    keeps at most ``_RENDER_CONCURRENCY`` decodes (and their memory) live. Also
    retrieves any exception so a timed-out task's error is never "never retrieved"."""
    _render_semaphore.release()
    if not task.cancelled():
        task.exception()  # consume; result-bearing tasks return None here


async def _render_bounded(
    settings, data: bytes, *, max_width: int | None, what: str, force_jpeg: bool = False
) -> tuple[bytes, str]:
    """Decode+downscale ``data`` on an offload thread under a wall-clock timeout
    AND a process-wide concurrency bound.

    The single seam that applies the per-request time bound (design §4): the
    CPU-bound :func:`render_page` runs via ``asyncio.to_thread`` so a wedged
    decode never blocks the loop, wrapped in ``asyncio.wait_for`` so the AWAIT can
    never spin past ``opds_pse_request_timeout_seconds``. Because that timeout can
    only cancel the await — not the un-killable thread — the render is additionally
    gated by ``_render_semaphore`` (:data:`_RENDER_CONCURRENCY`), whose permit is
    held for the thread's whole lifetime (released in :func:`_release_render_permit`
    on real completion, via ``shield`` so the timeout does not detach the task from
    its callback); THAT is what bounds aggregate render memory/threads under a
    flood. Over-budget → 503; an over-cap/corrupt/undecodable image → a bounded
    502; both are logged. Returns ``(encoded_bytes, content_type)``."""
    await _render_semaphore.acquire()
    task = asyncio.ensure_future(
        asyncio.to_thread(
            render_page,
            data,
            max_width=max_width,
            max_pixels=settings.opds_pse_max_pixels,
            force_jpeg=force_jpeg,
        )
    )
    task.add_done_callback(_release_render_permit)
    try:
        # shield so a wait_for timeout cancels only the wait, leaving the task (and
        # its permit-releasing callback) attached to the still-running thread.
        return await asyncio.wait_for(
            asyncio.shield(task),
            timeout=settings.opds_pse_request_timeout_seconds,
        )
    except (asyncio.TimeoutError, TimeoutError) as exc:
        logger.warning("opds render timed out (%s)", what)
        raise ApiError(503, f"render of {what} timed out") from exc
    except ImageRenderError as exc:
        logger.warning("opds render refused (%s): %s", what, exc)
        raise ApiError(502, f"{what} could not be rendered") from exc


def _series_nav_entry(base_path: str, row: SeriesRow) -> Entry:
    """One navigation entry linking into a series' acquisition feed — the
    shape shared by the All Series shelf and the search feed (FRG-OPDS-001,
    FRG-OPDS-007)."""
    return Entry(
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


def _series_matches(row: SeriesRow, folded_query: str) -> bool:
    """Case-folded containment of the (already folded) query in the series'
    stored matching key or any alias folded the same way (FRG-OPDS-007)."""
    if folded_query in row.matching_key:
        return True
    return any(
        folded_query in matching_key(alias)
        for alias in decode_aliases(row.aliases, series_id=row.id)
    )


def _issue_file_entry(
    base_path: str,
    series: SeriesRow,
    issue_file: IssueFileRow,
    issue: IssueRow,
    cover_url: str,
) -> Entry:
    """One acquisition entry for a downloadable issue-file, built from DB
    fields only (FRG-OPDS-002, FRG-OPDS-008, FRG-OPDS-011).

    Reads ``issue_file.page_count`` straight from the row (NO archive I/O at feed
    render — the M1 zero-I/O invariant): a POSITIVE count means the archive is
    listable with pages, so an OPDS-PSE stream link is emitted alongside the
    whole-file acquisition link (PSE is strictly additive — a non-PSE reader
    ignores it); a NULL (unlistable/legacy) OR 0-page count emits no PSE link.
    Image/thumbnail links point
    at the local first-page cover endpoint ONLY when the series has no remote
    ComicVine cover cached (``cover_cached_at is None``); when a remote cover
    exists the existing series cover-cache URL is kept unchanged."""
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

    links: list[Link] = [
        Link(
            href=f"{base_path}/file/{issue_file.id}",
            rel=REL_ACQUISITION,
            type=media_type_for(issue_file.path),
        ),
    ]
    if issue_file.page_count:
        # A POSITIVE count only: a NULL (unlistable/legacy) OR a 0-page count (a
        # listable but image-less zip) advertises no PSE stream — a 0-page link
        # would promise pages a reader then cannot fetch.
        # Literal ``{pageNumber}``/``{maxWidth}`` braces (doubled in the f-string)
        # pass through the atom escaper unescaped — a PSE reader expands them.
        links.append(
            Link(
                href=f"{base_path}/page/{issue_file.id}/{{pageNumber}}?width={{maxWidth}}",
                rel=REL_PSE_STREAM,
                type=_PSE_IMAGE_TYPE,
                pse_count=issue_file.page_count,
            )
        )

    if series.cover_cached_at is not None:
        image_href = cover_url
        thumb_href = cover_url
    else:
        image_href = f"{base_path}/cover/{issue_file.id}"
        thumb_href = f"{base_path}/cover/{issue_file.id}?thumbnail"
    links.append(Link(href=image_href, rel=REL_IMAGE, type=_PSE_IMAGE_TYPE))
    links.append(Link(href=thumb_href, rel=REL_THUMBNAIL, type=_PSE_IMAGE_TYPE))

    return Entry(
        id=f"{base_path}/file/{issue_file.id}",
        title=title,
        updated=updated,
        links=tuple(links),
    )
