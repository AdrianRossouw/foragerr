"""A minimal, escaping-by-construction OPDS 1.2 Atom feed builder
(FRG-OPDS-001, FRG-OPDS-002, FRG-OPDS-006).

Everything the builder emits passes through :func:`_escape` (element text) or
:func:`_quoteattr` (attribute values), so no caller can inject markup into a
feed by way of a series title, issue title or filename — the W7 anti-pattern
from the Mylar OPDS analysis. Escaping is implemented locally rather than
pulled from a stdlib SAX helper module, so this module constructs no XML
*parser* at all — it is purely a serializer — keeping it clear of the
untrusted-XML-parser ban (FRG-SEC-002). The builder reads only the values
handed to it: it never
touches the filesystem or an archive, which is what keeps feed rendering at
zero archive I/O (FRG-OPDS-002).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


#: Control characters XML 1.0 forbids even when escaped — the C0 range minus the
#: three it permits (``\t`` #x09, ``\n`` #x0A, ``\r`` #x0D), plus DEL (#x7F). A
#: single one of these in a title makes the WHOLE feed non-well-formed, so a
#: reader rejects the entire page; ``str.translate`` deletes them (mapping each
#: ordinal to ``None``).
_XML_ILLEGAL = dict.fromkeys(
    [*range(0x00, 0x09), 0x0B, 0x0C, *range(0x0E, 0x20), 0x7F], None
)


def _escape(value: str) -> str:
    """Escape XML element text: strip XML-illegal control chars, then ``&``
    first, then ``<`` and ``>``."""
    cleaned = value.translate(_XML_ILLEGAL)
    return cleaned.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _quoteattr(value: str) -> str:
    """Escape and double-quote an XML attribute value (also escapes ``"``)."""
    escaped = _escape(value).replace('"', "&quot;")
    return f'"{escaped}"'

# --- namespaces & OPDS link/type vocabulary ---------------------------------

ATOM_NS = "http://www.w3.org/2005/Atom"
OPENSEARCH_NS = "http://a9.com/-/spec/opensearch/1.1/"
OPDS_NS = "http://opds-spec.org/2010/catalog"

#: OPDS catalog feed kinds — the ``type`` attribute distinguishes a browse
#: (navigation) feed from a feed of downloadable issues (acquisition).
NAV_KIND = "application/atom+xml; profile=opds-catalog; kind=navigation"
ACQ_KIND = "application/atom+xml; profile=opds-catalog; kind=acquisition"

#: OPDS relation URIs.
REL_SELF = "self"
REL_START = "start"
REL_SUBSECTION = "subsection"
REL_SEARCH = "search"
REL_ACQUISITION = "http://opds-spec.org/acquisition"
REL_IMAGE = "http://opds-spec.org/image"
REL_THUMBNAIL = "http://opds-spec.org/image/thumbnail"

#: Media type of an OpenSearch description document (FRG-OPDS-007).
OPENSEARCH_DESC_KIND = "application/opensearchdescription+xml"


@dataclass(frozen=True)
class Link:
    href: str
    rel: str | None = None
    type: str | None = None


@dataclass(frozen=True)
class Entry:
    id: str
    title: str
    updated: dt.datetime
    links: tuple[Link, ...] = ()
    authors: tuple[str, ...] = ()
    summary: str | None = None


@dataclass(frozen=True)
class Feed:
    id: str
    title: str
    updated: dt.datetime
    self_url: str
    #: navigation / pagination links (next/previous/first/last/start).
    links: tuple[Link, ...] = ()
    entries: tuple[Entry, ...] = ()
    #: OpenSearch paging counters (FRG-OPDS-006); omitted when ``None``.
    total_results: int | None = None
    items_per_page: int | None = None
    start_index: int | None = None


def _fmt_ts(ts: dt.datetime) -> str:
    """RFC 3339 / Atom timestamp in UTC. Naive datetimes are read as UTC
    (the DB stores UTC via ``foragerr.db.base.utcnow``)."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=dt.timezone.utc)
    return ts.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _link_el(link: Link) -> str:
    parts = ["<link"]
    if link.rel is not None:
        parts.append(f" rel={_quoteattr(link.rel)}")
    if link.type is not None:
        parts.append(f" type={_quoteattr(link.type)}")
    parts.append(f" href={_quoteattr(link.href)}")
    parts.append("/>")
    return "".join(parts)


def _entry_el(entry: Entry) -> str:
    parts = [
        "<entry>",
        f"<id>{_escape(entry.id)}</id>",
        f"<title>{_escape(entry.title)}</title>",
        f"<updated>{_fmt_ts(entry.updated)}</updated>",
    ]
    for name in entry.authors:
        parts.append(f"<author><name>{_escape(name)}</name></author>")
    if entry.summary is not None:
        parts.append(f'<summary type="text">{_escape(entry.summary)}</summary>')
    parts.extend(_link_el(link) for link in entry.links)
    parts.append("</entry>")
    return "".join(parts)


def render_feed(feed: Feed) -> str:
    """Serialize ``feed`` to an OPDS 1.2 Atom document string."""
    parts = ['<?xml version="1.0" encoding="UTF-8"?>']
    parts.append(
        f"<feed xmlns={_quoteattr(ATOM_NS)} "
        f"xmlns:opensearch={_quoteattr(OPENSEARCH_NS)} "
        f"xmlns:opds={_quoteattr(OPDS_NS)}>"
    )
    parts.append(f"<id>{_escape(feed.id)}</id>")
    parts.append(f"<title>{_escape(feed.title)}</title>")
    parts.append(f"<updated>{_fmt_ts(feed.updated)}</updated>")
    parts.append(_link_el(Link(href=feed.self_url, rel=REL_SELF)))
    parts.extend(_link_el(link) for link in feed.links)
    if feed.total_results is not None:
        parts.append(
            f"<opensearch:totalResults>{int(feed.total_results)}"
            "</opensearch:totalResults>"
        )
    if feed.items_per_page is not None:
        parts.append(
            f"<opensearch:itemsPerPage>{int(feed.items_per_page)}"
            "</opensearch:itemsPerPage>"
        )
    if feed.start_index is not None:
        parts.append(
            f"<opensearch:startIndex>{int(feed.start_index)}</opensearch:startIndex>"
        )
    parts.extend(_entry_el(entry) for entry in feed.entries)
    parts.append("</feed>")
    return "".join(parts)


def render_opensearch_description(
    *, short_name: str, description: str, template: str, results_type: str
) -> str:
    """Serialize an OpenSearch 1.1 description document (FRG-OPDS-007).

    ``template`` is the OpenSearch URL template and carries the LITERAL
    ``{searchTerms}`` placeholder — it is an attribute value like any other
    here (quoted/escaped), never interpolated. Built through the same
    escaping serializer discipline as the feeds: this module still constructs
    no XML parser (FRG-SEC-002).
    """
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<OpenSearchDescription xmlns={_quoteattr(OPENSEARCH_NS)}>"
        f"<ShortName>{_escape(short_name)}</ShortName>"
        f"<Description>{_escape(description)}</Description>"
        "<InputEncoding>UTF-8</InputEncoding>"
        "<OutputEncoding>UTF-8</OutputEncoding>"
        f"<Url type={_quoteattr(results_type)} template={_quoteattr(template)}/>"
        "</OpenSearchDescription>"
    )
