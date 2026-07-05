"""Newznab RSS/XML parsing → normalized releases (FRG-IDX-006, FRG-IDX-007).

Converts a Newznab feed (already hardened-parsed by
:mod:`foragerr.indexers.xml`) into :class:`~foragerr.releases.ReleaseCandidate`
records, stamping each with indexer attribution and the query tier. A Newznab
``<error code>`` document maps to a typed failure (auth / limit / unavailable)
rather than an empty result set (FRG-IDX-006). Individual malformed items are
skipped and counted while the batch survives; per-indexer guid de-duplication
happens here at parse time (FRG-IDX-007).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from xml.etree.ElementTree import Element

from foragerr.indexers.errors import (
    IndexerAuthError,
    IndexerFailure,
    IndexerLimitError,
    IndexerMalformedError,
    IndexerUnavailable,
)
from foragerr.indexers.xml import DEFAULT_MAX_BYTES, parse_indexer_xml
from foragerr.releases import ReleaseCandidate

#: Newznab error codes → typed failures (FRG-IDX-006). Auth and limit are the
#: two the spec names explicitly; the rest degrade to a typed unavailable.
_AUTH_CODES = frozenset({"100", "101", "102", "910"})
_LIMIT_CODES = frozenset({"500", "501"})


@dataclass(frozen=True, slots=True)
class IndexerContext:
    """Attribution stamped onto every candidate from one indexer (FRG-IDX-007)."""

    indexer_id: int
    indexer_name: str
    indexer_priority: int


@dataclass(frozen=True, slots=True)
class ParseResult:
    """Normalized releases plus the counts of items dropped from this page.

    ``skipped`` = items dropped as malformed; ``duplicates`` = items dropped as
    guid-duplicates of ones already seen. Both are dropped from ``candidates``
    but the indexer *did* return them, so pagination must count them when
    reconstructing the page size (FRG-IDX-005) — otherwise dedup fakes a short
    page and search stops early.
    """

    candidates: list[ReleaseCandidate]
    skipped: int
    duplicates: int = 0


def _localname(tag: str) -> str:
    """Strip an XML namespace: ``{ns}attr`` → ``attr``."""
    return tag.rsplit("}", 1)[-1]


def _error_to_failure(root: Element) -> IndexerFailure:
    code = (root.get("code") or "").strip()
    description = (root.get("description") or "").strip() or "Newznab error"
    if code in _AUTH_CODES:
        return IndexerAuthError(f"indexer auth failure (code {code}): {description}")
    if code in _LIMIT_CODES:
        return IndexerLimitError(f"indexer request limit (code {code}): {description}")
    return IndexerUnavailable(f"indexer error (code {code}): {description}")


def _parse_pubdate(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _newznab_attrs(item: Element) -> dict[str, str]:
    """Collect ``<newznab:attr name= value=>`` name/value pairs (last wins,
    except ``category`` which is multi-valued and handled separately)."""
    attrs: dict[str, str] = {}
    for child in item:
        if _localname(child.tag) == "attr":
            name = child.get("name")
            value = child.get("value")
            if name is not None and value is not None:
                attrs[name] = value
    return attrs


def _categories(item: Element) -> tuple[int, ...]:
    cats: list[int] = []
    for child in item:
        if _localname(child.tag) == "attr" and child.get("name") == "category":
            value = child.get("value")
            if value and value.isdigit():
                cats.append(int(value))
    return tuple(cats)


def _child_text(item: Element, name: str) -> str | None:
    for child in item:
        if _localname(child.tag) == name:
            return (child.text or "").strip() or None
    return None


def _enclosure(item: Element) -> tuple[str | None, int | None]:
    """Return ``(url, length)`` from the ``<enclosure>`` element if present."""
    for child in item:
        if _localname(child.tag) == "enclosure":
            url = child.get("url")
            length = child.get("length")
            size = int(length) if length and length.isdigit() else None
            return url, size
    return None, None


def _size_bytes(item: Element, attrs: dict[str, str], enclosure_size: int | None) -> int | None:
    raw = attrs.get("size") or _child_text(item, "size")
    if raw and raw.isdigit():
        return int(raw)
    return enclosure_size


def _map_item(item: Element, tier: int, ctx: IndexerContext) -> ReleaseCandidate:
    """Map one ``<item>`` to a candidate, or raise ``IndexerMalformedError``
    for an item missing the required identity/download fields."""
    guid = _child_text(item, "guid")
    title = _child_text(item, "title")
    enclosure_url, enclosure_size = _enclosure(item)
    link = enclosure_url or _child_text(item, "link")
    if not guid or not title or not link:
        raise IndexerMalformedError("item missing guid/title/link")
    attrs = _newznab_attrs(item)
    attrs.pop("category", None)  # promoted to the typed categories tuple
    return ReleaseCandidate(
        guid=guid,
        title=title,
        link=link,
        indexer_id=ctx.indexer_id,
        indexer_name=ctx.indexer_name,
        indexer_priority=ctx.indexer_priority,
        query_tier=tier,
        size_bytes=_size_bytes(item, attrs, enclosure_size),
        pub_date=_parse_pubdate(_child_text(item, "pubDate")),
        categories=_categories(item),
        attributes=attrs,
    )


def parse_newznab_feed(
    data: bytes | str,
    ctx: IndexerContext,
    *,
    query_tier: int = 0,
    max_bytes: int | None = DEFAULT_MAX_BYTES,
    seen_guids: set[str] | None = None,
) -> ParseResult:
    """Parse a Newznab feed into normalized, de-duplicated candidates.

    Raises the typed failure for an ``<error code>`` document or a
    hostile/malformed root (via the hardened parser). ``seen_guids`` lets the
    caller carry per-indexer de-dup across paged fetches (FRG-IDX-007).
    """
    root = parse_indexer_xml(data, max_bytes=max_bytes)
    if _localname(root.tag) == "error":
        raise _error_to_failure(root)

    seen = seen_guids if seen_guids is not None else set()
    candidates: list[ReleaseCandidate] = []
    skipped = 0
    duplicates = 0
    for item in root.iter():
        if _localname(item.tag) != "item":
            continue
        try:
            candidate = _map_item(item, query_tier, ctx)
        except IndexerMalformedError:
            skipped += 1  # one bad item never fails the batch (FRG-IDX-006)
            continue
        if candidate.guid in seen:
            duplicates += 1  # per-indexer guid de-dup, but the item WAS returned
            continue  # (FRG-IDX-007) — counted for pagination (FRG-IDX-005)
        seen.add(candidate.guid)
        candidates.append(candidate)
    return ParseResult(candidates=candidates, skipped=skipped, duplicates=duplicates)
