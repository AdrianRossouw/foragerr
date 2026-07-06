"""Outbound HTTP choke point (FRG-NFR-006, FRG-SEC-001).

ALL outbound HTTP traffic flows through :class:`HttpClientFactory` — no other
module in ``backend/src`` may import ``httpx``/``requests`` (enforced by the
static-guard test). See :mod:`foragerr.http.factory` for the guarantees and
:mod:`foragerr.http.egress` for the SSRF policy and its documented
DNS-rebinding residual (RISK-025).
"""

from foragerr.http.egress import EXTERNAL, LOCAL_SERVICE, EgressValidator, Resolver
from foragerr.http.errors import (
    EgressPolicyError,
    OutboundHttpError,
    ResponseTooLargeError,
    TooManyRedirectsError,
)
from foragerr.http.factory import (
    MAX_REDIRECTS,
    FetchResult,
    HttpClientFactory,
    OutboundClient,
    StreamedResponse,
)
from foragerr.http.headers import parse_retry_after

__all__ = [
    "EXTERNAL",
    "LOCAL_SERVICE",
    "MAX_REDIRECTS",
    "EgressPolicyError",
    "EgressValidator",
    "FetchResult",
    "HttpClientFactory",
    "OutboundClient",
    "OutboundHttpError",
    "Resolver",
    "ResponseTooLargeError",
    "StreamedResponse",
    "TooManyRedirectsError",
    "parse_retry_after",
]
