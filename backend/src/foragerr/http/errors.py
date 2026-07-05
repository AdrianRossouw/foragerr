"""Error hierarchy for the outbound HTTP choke point (FRG-NFR-006, FRG-SEC-001).

Every message carried by these exceptions has already passed through
:func:`foragerr.logging.redact`, so a URL embedded in an error can never leak
an ``api_key``-shaped query parameter or a registered secret even if the
exception text is surfaced outside the logging pipeline (FRG-NFR-008).
"""

from __future__ import annotations


class OutboundHttpError(Exception):
    """Base class for failures raised by the outbound HTTP factory."""


class EgressPolicyError(OutboundHttpError):
    """A request hop was refused by the egress policy before any connection
    was made (FRG-SEC-001).

    Attributes:
        url: the offending URL, redacted.
        offending_address: the resolved/interpreted IP address that violated
            the policy, when the refusal was address-based (``None`` for
            scheme/parse refusals).
        reason: short machine-readable cause, e.g. ``loopback``,
            ``private (RFC 1918)``, ``forbidden scheme``.
    """

    def __init__(
        self,
        message: str,
        *,
        url: str,
        offending_address: str | None = None,
        reason: str,
    ) -> None:
        super().__init__(message)
        self.url = url
        self.offending_address = offending_address
        self.reason = reason


class TooManyRedirectsError(OutboundHttpError):
    """The manual redirect walk exceeded the bounded hop count (FRG-NFR-006)."""


class ResponseTooLargeError(OutboundHttpError):
    """A response body exceeded the configured byte cap; the read was aborted
    and no partial body was returned to the caller (FRG-NFR-006)."""
