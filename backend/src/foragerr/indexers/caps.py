"""Newznab capabilities (``?t=caps``) model, parsing, and TTL cache
(FRG-IDX-004).

The caps response drives category selection (7030 Books/Comics with a
conservative fallback), page-size limits, and search-mode support flags. It is
cached per indexer with a ~7-day lifetime so repeat operations reuse it. A
probe failure degrades to conservative defaults recorded on the row rather than
blocking configuration (:data:`CONSERVATIVE_CAPS`).

This module is pure: parsing runs through the hardened XML parser
(:mod:`foragerr.indexers.xml`); the actual HTTP probe lives in the client
(:mod:`foragerr.indexers.newznab`).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from foragerr.indexers.settings import COMICS_CATEGORY
from foragerr.indexers.xml import parse_indexer_xml

#: Caps cache lifetime — ~7 days (FRG-IDX-004).
CAPS_TTL_SECONDS = 7 * 24 * 60 * 60

#: Conservative page-size default when caps is silent/unavailable.
DEFAULT_PAGE_SIZE = 100


@dataclass(frozen=True, slots=True)
class Capabilities:
    """Resolved indexer capabilities from a caps response."""

    page_size_max: int = DEFAULT_PAGE_SIZE
    page_size_default: int = DEFAULT_PAGE_SIZE
    #: Available category id → name (the options offered in settings).
    categories: dict[int, str] = field(default_factory=dict)
    search_available: bool = True
    book_search_available: bool = False
    #: True when these are conservative fallbacks, not live caps (FRG-IDX-004).
    degraded: bool = False

    def resolve_categories(self, preferred: list[int]) -> list[int]:
        """The categories to actually search: the preferred set, defaulting to
        7030 and always including it as a conservative fallback when caps omits
        the preferred ones (FRG-IDX-004)."""
        chosen = [c for c in preferred if c] or [COMICS_CATEGORY]
        if not self.categories:  # no caps knowledge — trust the configured set
            return chosen
        known = [c for c in chosen if c in self.categories]
        return known or [COMICS_CATEGORY]


#: The conservative fallback used when a caps probe fails (FRG-IDX-004).
CONSERVATIVE_CAPS = Capabilities(
    categories={COMICS_CATEGORY: "Comics"},
    search_available=True,
    book_search_available=False,
    degraded=True,
)


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_caps(data: bytes | str) -> Capabilities:
    """Parse a caps XML response into :class:`Capabilities`.

    Uses the hardened parser; a malformed body raises
    :class:`~foragerr.indexers.errors.IndexerMalformedError` (the caller
    decides whether to degrade)."""
    root = parse_indexer_xml(data)
    page_max = DEFAULT_PAGE_SIZE
    page_default = DEFAULT_PAGE_SIZE
    categories: dict[int, str] = {}
    search_available = True
    book_search_available = False

    for node in root.iter():
        name = _localname(node.tag)
        if name == "limits":
            page_max = _int(node.get("max"), page_max)
            page_default = _int(node.get("default"), page_default)
        elif name == "search":
            search_available = node.get("available", "yes") == "yes"
        elif name == "book-search":
            book_search_available = node.get("available", "no") == "yes"
        elif name in ("category", "subcat"):
            cid = _int(node.get("id"), 0)
            label = node.get("name")
            if cid and label:
                categories[cid] = label

    return Capabilities(
        page_size_max=page_max,
        page_size_default=page_default,
        categories=categories,
        search_available=search_available,
        book_search_available=book_search_available,
        degraded=False,
    )


def _int(value: str | None, default: int) -> int:
    if value and value.strip().lstrip("-").isdigit():
        return int(value)
    return default


class CapsCache:
    """In-memory per-indexer caps cache with a TTL (FRG-IDX-004).

    ``clock`` is injectable for tests (default monotonic seconds).
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = CAPS_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._entries: dict[int, tuple[float, Capabilities]] = {}

    def get(self, indexer_id: int) -> Capabilities | None:
        """The cached caps for an indexer if still within its TTL, else None."""
        entry = self._entries.get(indexer_id)
        if entry is None:
            return None
        stored_at, caps = entry
        if self._clock() - stored_at > self._ttl:
            del self._entries[indexer_id]
            return None
        return caps

    def put(self, indexer_id: int, caps: Capabilities) -> None:
        self._entries[indexer_id] = (self._clock(), caps)

    def clear(self) -> None:
        self._entries.clear()
