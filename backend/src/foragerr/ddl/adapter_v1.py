"""Versioned GetComics HTML adapter, v1 (FRG-DDL-003).

ALL GetComics HTML parsing lives here, behind a version boundary, so a site
redesign is a *fixture refresh + adapter_v2* — never a code-archaeology dig
scattered across the provider (the mylar-ddl §3.1 DOM-coupling weakness). Two
entry points parse the two page kinds:

- :func:`parse_search_page` — a ``/?s=`` results page → :class:`ParsedPost`
  records + the "older posts" next-page URL.
- :func:`parse_post_page` — one article page → :class:`RawPostLink` download
  anchors, grouped by the quality section they appear under.

Parsing uses ONLY the standard-library :class:`html.parser.HTMLParser` — no
second parser is introduced (defusedxml stays the one XML site; HTML gets this
one adapter). A structural miss raises :class:`~foragerr.ddl.errors.AdapterDrift`
(never an unhandled exception, never a mis-parse): the search provider turns
that into zero results + a provider-health warning + shared back-off.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from foragerr.ddl.errors import AdapterDrift

#: Marker classes/ids identifying the site content shell. Their ABSENCE on a
#: search page is the drift signal (an empty search still renders the shell).
_CONTENT_MARKERS = frozenset({"content", "main", "primary", "site-content"})

#: Title fragments marking a weekly-roundup post (skipped, FRG-DDL-002).
_ROUNDUP_FRAGMENTS = ("weekly", "week+", "mega pack", "0-day", "0 day")

_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(k|m|g|t)b?\b", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_SIZE_UNIT = {"k": 1024, "m": 1024**2, "g": 1024**3, "t": 1024**4}


@dataclass(frozen=True, slots=True)
class ParsedPost:
    """One search-result post (FRG-DDL-002/003)."""

    post_url: str
    title: str
    size_bytes: int | None
    pub_date: dt.datetime | None
    year: int | None

    @property
    def is_roundup(self) -> bool:
        """Weekly-roundup posts are skipped by the provider (FRG-DDL-002)."""
        low = self.title.lower()
        return any(fragment in low for fragment in _ROUNDUP_FRAGMENTS)


@dataclass(frozen=True, slots=True)
class SearchPage:
    """The parse of one search-results page."""

    posts: list[ParsedPost]
    next_page_url: str | None


@dataclass(frozen=True, slots=True)
class RawPostLink:
    """One download anchor on a post page, before host/quality typing."""

    quality_label: str
    host_label: str
    url: str


def _norm(text: str) -> str:
    return " ".join((text or "").replace("–", "-").split()).strip()


def _parse_size(text: str) -> int | None:
    match = _SIZE_RE.search(text or "")
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).lower()
    return int(value * _SIZE_UNIT[unit])


def _parse_year(text: str) -> int | None:
    match = _YEAR_RE.search(text or "")
    return int(match.group(0)) if match else None


def _parse_datetime(value: str) -> dt.datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return parsed


def _attr(attrs: list[tuple[str, str | None]], name: str) -> str | None:
    for key, value in attrs:
        if key == name:
            return value
    return None


def _classes(attrs: list[tuple[str, str | None]]) -> set[str]:
    return set((_attr(attrs, "class") or "").split())


class _SearchParser(HTMLParser):
    """Extracts posts + the next-page link from a search-results page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.content_seen = False
        self.posts: list[ParsedPost] = []
        self.next_url: str | None = None
        self._cur: dict[str, str | None] | None = None
        self._capture: str | None = None

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        classes = _classes(attrs)
        ident = (_attr(attrs, "id") or "").lower()
        if ident in _CONTENT_MARKERS or classes & _CONTENT_MARKERS or tag == "main":
            self.content_seen = True
        if tag == "article":
            self._cur = {"link": None, "title": "", "info": "", "date": None}
            return
        if self._cur is not None:
            if tag == "a" and self._cur["link"] is None:
                href = _attr(attrs, "href")
                if href:
                    self._cur["link"] = href
            if tag in ("h1", "h2", "h3") and (
                "post-title" in classes or "entry-title" in classes
            ):
                self._capture = "title"
            elif tag == "p" and "post-info" in classes:
                self._capture = "info"
            elif tag == "time":
                self._cur["date"] = _attr(attrs, "datetime")
        if tag == "a" and (
            "pagination-next" in classes
            or "nextpostslink" in classes
            or _attr(attrs, "rel") == "next"
        ):
            href = _attr(attrs, "href")
            if href:
                self.next_url = href

    def handle_data(self, data: str) -> None:
        if self._cur is not None and self._capture is not None:
            self._cur[self._capture] = (self._cur[self._capture] or "") + data

    def handle_endtag(self, tag: str) -> None:
        if tag in ("h1", "h2", "h3", "p") and self._capture:
            self._capture = None
        if tag == "article" and self._cur is not None:
            self._finish_article(self._cur)
            self._cur = None

    def _finish_article(self, cur: dict[str, str | None]) -> None:
        link = cur["link"]
        title = _norm(cur["title"] or "")
        if not link or not title:
            # An <article> with neither a link nor a title means the selectors
            # no longer match the DOM — a drift signal, not an empty result.
            raise AdapterDrift("search", "article missing post link/title")
        info = cur["info"] or ""
        self.posts.append(
            ParsedPost(
                post_url=link,
                title=title,
                size_bytes=_parse_size(info),
                pub_date=_parse_datetime(cur["date"] or ""),
                year=_parse_year(info) or _parse_year(title),
            )
        )


class _PostParser(HTMLParser):
    """Extracts quality-grouped download anchors from a post page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.aio_seen = False
        self.links: list[RawPostLink] = []
        self._div_stack: list[bool] = []  # True where the div is an aio-pulse
        self._quality = ""
        self._heading_capture = False
        self._heading_buf = ""
        self._anchor: dict[str, str] | None = None
        self._anchor_buf = ""

    @property
    def _in_aio(self) -> bool:
        return any(self._div_stack)

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        classes = _classes(attrs)
        if tag == "div":
            is_aio = "aio-pulse" in classes
            if is_aio:
                self.aio_seen = True
            self._div_stack.append(is_aio)
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "strong", "p") and (
            "quality" in classes or "aio-title" in classes
        ):
            self._heading_capture = True
            self._heading_buf = ""
            return
        if tag == "a" and self._in_aio:
            href = _attr(attrs, "href") or ""
            self._anchor = {"href": href, "title": _attr(attrs, "title") or ""}
            self._anchor_buf = ""

    def handle_data(self, data: str) -> None:
        if self._heading_capture:
            self._heading_buf += data
        elif self._anchor is not None:
            self._anchor_buf += data

    def handle_endtag(self, tag: str) -> None:
        if tag in ("h1", "h2", "h3", "h4", "h5", "strong", "p") and self._heading_capture:
            self._quality = _norm(self._heading_buf)
            self._heading_capture = False
        elif tag == "a" and self._anchor is not None:
            label = _norm(self._anchor["title"]) or _norm(self._anchor_buf)
            href = _norm(self._anchor["href"])
            if href:
                self.links.append(
                    RawPostLink(
                        quality_label=self._quality,
                        host_label=label,
                        url=href,
                    )
                )
            self._anchor = None
        elif tag == "div" and self._div_stack:
            self._div_stack.pop()


def parse_search_page(html: str, *, base_url: str) -> SearchPage:
    """Parse a GetComics ``/?s=`` results page (FRG-DDL-002/003).

    Raises :class:`AdapterDrift` when the content shell is absent (the page
    structure no longer matches) — the caller degrades to zero results + a
    health warning. An empty *but well-formed* results page yields no posts and
    does NOT drift.
    """
    parser = _SearchParser()
    try:
        parser.feed(html or "")
    except AdapterDrift:
        raise
    except Exception as exc:  # noqa: BLE001 — any parse blow-up is drift, not a crash
        raise AdapterDrift("search", f"unparseable HTML: {exc}") from exc
    if not parser.content_seen:
        raise AdapterDrift("search", "content shell not found")
    next_url = urljoin(base_url, parser.next_url) if parser.next_url else None
    posts = [
        ParsedPost(
            post_url=urljoin(base_url, p.post_url),
            title=p.title,
            size_bytes=p.size_bytes,
            pub_date=p.pub_date,
            year=p.year,
        )
        for p in parser.posts
    ]
    return SearchPage(posts=posts, next_page_url=next_url)


def parse_post_page(html: str, *, base_url: str) -> list[RawPostLink]:
    """Parse a GetComics article page into download anchors (FRG-DDL-003/004).

    Raises :class:`AdapterDrift` when no download block is present at all (the
    selectors no longer match). Relative hrefs are resolved against ``base_url``.
    """
    parser = _PostParser()
    try:
        parser.feed(html or "")
    except AdapterDrift:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AdapterDrift("post", f"unparseable HTML: {exc}") from exc
    if not parser.aio_seen:
        raise AdapterDrift("post", "no download block found")
    return [
        RawPostLink(
            quality_label=link.quality_label,
            host_label=link.host_label,
            url=urljoin(base_url, link.url),
        )
        for link in parser.links
    ]


def url_host(url: str) -> str:
    """The lowercased host of a URL (empty for a malformed one)."""
    return (urlsplit(url).hostname or "").lower()


__all__ = [
    "ParsedPost",
    "RawPostLink",
    "SearchPage",
    "parse_post_page",
    "parse_search_page",
    "url_host",
]
