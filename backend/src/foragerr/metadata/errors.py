"""Typed ComicVine client exceptions (FRG-META-001).

Distinct upstream conditions raise distinct typed errors — never a bare
transport error, an ``httpx`` internal, or a silent ``None``. The outbound
factory has already redacted any URL/api_key it logged (FRG-NFR-008), so these
messages are safe to surface; callers still MUST NOT interpolate raw ComicVine
content or keys into them.

Relationship to the HTTP layer: egress/size/redirect refusals from the shared
factory (:class:`foragerr.http.errors.OutboundHttpError`) and raw transport
timeouts are wrapped as :class:`ComicVineUnavailable` (the network could not
deliver a usable response), keeping ``httpx`` types from leaking to callers.
"""

from __future__ import annotations


class ComicVineError(Exception):
    """Base class for every ComicVine client failure."""


class ComicVineAuthError(ComicVineError):
    """Authentication failed — missing/invalid API key (HTTP 401/403 or CV
    ``status_code`` 100)."""


class ComicVineRateLimited(ComicVineError):
    """ComicVine signalled rate limiting (HTTP 420/429 or a detected ban
    page). The shared limiter has been told to back off; health is degraded."""

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ComicVineMalformedResponse(ComicVineError):
    """The response was not the expected JSON shape (non-JSON body, wrong
    top-level type, or an unexpected CV error status)."""


class ComicVineUnavailable(ComicVineError):
    """ComicVine could not be reached or returned a server/transport error
    (timeout, 5xx, egress refusal, oversize body)."""


class CoverHostNotAllowed(ComicVineError):
    """A cover image URL pointed at a host outside the configured allowlist
    (FRG-META-013 — image host allowlisted via config, not hardcoded)."""
