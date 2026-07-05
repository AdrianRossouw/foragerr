"""Typed errors for the built-in DDL (GetComics) area (FRG-DDL-003..012).

Kept in their own module so the adapter, search provider, client, and download
engine can raise/catch a shared typed vocabulary without importing each other.
"""

from __future__ import annotations


class DdlError(Exception):
    """Base for every DDL-area error."""


class AdapterDrift(DdlError):
    """A GetComics page no longer matches the versioned adapter's selectors.

    Raised by :mod:`foragerr.ddl.adapter_v1` on a structural miss (FRG-DDL-003)
    so the search provider degrades to zero results + a health warning +
    back-off, rather than mis-parsing or crashing. Carries the page kind and a
    short reason for the operator-facing health message.
    """

    def __init__(self, kind: str, reason: str) -> None:
        super().__init__(f"GetComics {kind} page drifted: {reason}")
        self.kind = kind
        self.reason = reason


class DdlDownloadError(DdlError):
    """A single download/verification attempt failed (FRG-DDL-008..010).

    Non-terminal by itself: the queue engine records the failed link type and
    fails over to the next untried host (FRG-DDL-005); host exhaustion is what
    makes the item terminally failed.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class OutboundNotAllowedError(DdlDownloadError):
    """A URL (or a redirect hop) is outside the provider scheme/host allowlist
    (FRG-DDL-012) — refused before any body is fetched."""


__all__ = [
    "AdapterDrift",
    "DdlDownloadError",
    "DdlError",
    "OutboundNotAllowedError",
]
