"""Typed download-client failures (FRG-DL-002/003).

The grab dispatch and tracking loop consume these typed failures rather than
bare transport errors, so a client problem at grab time is a *retryable command
failure* — the release cache entry stays valid and the grab is never silently
dropped (FRG-DL-002 scenario 3) — cleanly distinguished from a *grab-content
failure* (an NZB that will never validate), which should not be retried blindly.
"""

from __future__ import annotations


class DownloadClientError(Exception):
    """Base for every typed download-client failure."""


class NoDownloadClientError(DownloadClientError):
    """No enabled client matches the release's protocol (FRG-DL-002).

    A retryable/fallback-pending condition — the operator may enable a client —
    never a silently-dropped grab.
    """


class DownloadClientUnreachableError(DownloadClientError):
    """The protocol-matched client (or the indexer NZB fetch) was unreachable.

    Retryable: raised when the SAB API or the indexer NZB fetch fails at grab
    time. The caller treats it as a typed command failure leaving the release
    cache entry valid so the grab can be retried (FRG-DL-002 scenario 3).
    """


class GrabValidationError(DownloadClientError):
    """The fetched release content failed validation before upload (FRG-DL-003).

    Raised for empty / non-XML / segment-less NZB bytes, or an empty ``nzo_id``
    from SABnzbd — a grab failure carrying a human-readable reason. Distinct
    from :class:`DownloadClientUnreachableError`: the content itself is bad, so a
    blind retry of the same release will fail identically.
    """


__all__ = [
    "DownloadClientError",
    "DownloadClientUnreachableError",
    "GrabValidationError",
    "NoDownloadClientError",
]
