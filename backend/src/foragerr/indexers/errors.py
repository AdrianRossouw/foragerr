"""Typed indexer failures (FRG-IDX-006).

Newznab ``<error code>`` responses, HTTP status, transport failures, and
hostile/malformed XML all collapse into these four typed failures so the
back-off ladder and health surface can react precisely (auth vs limit vs
malformed vs unavailable) instead of to a generic error or a silent empty
result. Every failure carries whether it should *fast-forward* the ladder
(:attr:`IndexerFailure.fast_forward`) and any ``retry_after`` the server gave.
"""

from __future__ import annotations


class IndexerFailure(Exception):
    """Base for every typed indexer request failure.

    ``fast_forward`` marks failures (auth / request-limit) that should jump the
    back-off ladder rather than step one rung; ``retry_after`` carries a
    server-instructed wait in seconds when present.
    """

    fast_forward: bool = False

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class IndexerAuthError(IndexerFailure):
    """Invalid/missing API key — Newznab ``<error code="100/101">`` or HTTP
    401/403. Always fast-forwards the ladder (hammering a bad key is pointless)."""

    fast_forward = True


class IndexerLimitError(IndexerFailure):
    """Request/API limit reached — Newznab ``<error code="500">`` family or HTTP
    429. Fast-forwards the ladder and honors any Retry-After."""

    fast_forward = True


class IndexerMalformedError(IndexerFailure):
    """The response was not parseable as a Newznab feed — non-XML junk, a
    hostile entity payload, or a structurally invalid document. A typed parse
    failure, never a crash or a partial result (FRG-SEC-002)."""


class IndexerUnavailable(IndexerFailure):
    """The indexer could not be reached or returned a server/transport error
    (timeout, 5xx, egress refusal, oversize body)."""
