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

import datetime as dt
import logging
import math
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

from foragerr.security.paths import PathConfinementError, validate_under_root
from foragerr.opds.atom import (
    ACQ_KIND,
    NAV_KIND,
    OPENSEARCH_DESC_KIND,
    REL_ACQUISITION,
    REL_IMAGE,
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


def _cover_url(series_id: int) -> str:
    """Local cover-cache endpoint (FRG-META-013) — never a remote CDN URL."""
    return f"/api/v1/series/{series_id}/cover"


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
            series_count = await session.scalar(
                select(func.count()).select_from(SeriesRow)
            )
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
        kind). Paginated."""
        settings = request.app.state.settings
        page_size = _effective_page_size(count, settings)
        db = request.app.state.db
        async with db.read_session() as session:
            total, result = await _count_and_page(
                session,
                select(SeriesRow),
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
            )
            total, result = await _count_and_page(
                session,
                base_query,
                order_by=(IssueRow.ordering_key, IssueFileRow.id),
                page=page,
                page_size=page_size,
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
            _issue_file_entry(base_path, series, issue_file, issue, _cover_url(series.id))
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
