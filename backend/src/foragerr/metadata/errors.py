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

#: The ONE static credential-failure sentence (m2-lookup-error-surfacing
#: decision 5). Every surface that reports a :class:`ComicVineAuthError`
#: composes its own prefix around this constant — the lookup endpoint, the
#: add flow, the library-import scan/execute, the override validation — so
#: the wording can never drift between call sites. Static text, never the
#: exception's own message, so no key material can leak; API surfaces pair it
#: with the machine-readable ``field="comicvine_api_key"`` discriminator the
#: frontend classifies credential failures on.
COMICVINE_CREDENTIAL_MESSAGE = (
    "ComicVine rejected the API key (missing or invalid) — set comicvine_api_key"
)


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


class ComicVineBudgetExhausted(ComicVineError):
    """A per-path hourly request budget is exhausted (FRG-META-016).

    Raised by the shared rate gate BEFORE a request reaches the wire when the
    resource path's soft hourly ceiling (default 150, configurable, ≤200) has
    been consumed over the rolling one-hour window. This is a LOCAL decision —
    ComicVine saw nothing — so unlike :class:`ComicVineRateLimited` it does NOT
    flip the degraded/back-off state and never blocks the caller waiting for
    capacity. It carries the ``bucket`` (the normalized first path segment) and
    ``retry_after_seconds`` (a duration until the oldest admission ages out of
    the window), so a call site can defer cleanly and surface an honest resume
    time. Every raise is logged by the caller — a deferral is never silent.
    """

    def __init__(self, bucket: str, *, retry_after_seconds: float) -> None:
        super().__init__(
            f"comicvine hourly budget exhausted for path {bucket!r}; "
            f"resumes in ~{retry_after_seconds:.0f}s"
        )
        self.bucket = bucket
        self.retry_after_seconds = retry_after_seconds


class ComicVineMalformedResponse(ComicVineError):
    """The response was not the expected JSON shape (non-JSON body, wrong
    top-level type, or an unexpected CV error status)."""


class ComicVineUnavailable(ComicVineError):
    """ComicVine could not be reached or returned a server/transport error
    (timeout, 5xx, egress refusal, oversize body)."""


class CoverHostNotAllowed(ComicVineError):
    """A cover image URL pointed at a host outside the configured allowlist
    (FRG-META-013 — image host allowlisted via config, not hardcoded)."""
