"""The single outbound HTTP client factory (FRG-NFR-006, FRG-SEC-001).

Design (m1-foundation, decision 9): every outbound ``httpx.AsyncClient`` in
foragerr is built here — the one choke point where timeouts, TLS
verification, redirect bounds, response-size bounds, egress policy, and log
redaction are all enforced. The static-guard test keeps any other
``httpx``/``requests`` call site out of ``backend/src``.

Guarantees on every client this factory produces:

- explicit connect / read / write / pool timeouts from settings — nothing is
  ever unlimited;
- TLS certificate verification always on; the factory API deliberately
  exposes NO per-call or per-host opt-out parameter;
- ``follow_redirects=False`` — redirects are walked manually by
  :meth:`OutboundClient.request`, bounded at :data:`MAX_REDIRECTS` hops, and
  every hop (including the initial request) is re-validated by the egress
  policy (:mod:`foragerr.http.egress`);
- response bodies are streamed with a byte cap: oversize bodies — including
  servers that omit or lie in ``Content-Length`` — abort the read with a
  bounded error, never accumulate an unbounded buffer, and never hand a
  partial body to the caller;
- credentials/cookies supplied for the originating request are NOT forwarded
  to redirect hosts outside the original host (FRG-SEC-001);
- any URL logged or embedded in an error by this module passes through
  :func:`foragerr.logging.redact` first (FRG-NFR-008).

How later areas obtain clients
------------------------------
Build one :class:`HttpClientFactory` from settings at app startup, then:

- ``factory.external()`` — default profile for any host derived from
  external or config-supplied input (ComicVine, indexers, DDL, images);
  the full SSRF egress policy applies to every hop.
- ``factory.local_service(base_url)`` — for an integration whose base URL
  the operator configured explicitly (e.g. SABnzbd at
  ``settings.sabnzbd_url`` on a LAN address, field added by the DL change);
  that exact base-URL origin is allowed, everything else still gets the
  external policy.

Residual risk — DNS-rebinding TOCTOU: see :mod:`foragerr.http.egress`
(resolve-then-connect window, accepted residual per RISK-025).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable, Iterable, Mapping

import httpx

if TYPE_CHECKING:  # typing only — no runtime dependency direction change
    from foragerr.config import Settings

from foragerr.http.egress import (
    ALLOWED_SCHEMES,
    EXTERNAL,
    LOCAL_SERVICE,
    EgressValidator,
    Resolver,
)
from foragerr.http.errors import (
    EgressPolicyError,
    ResponseTooLargeError,
    TooManyRedirectsError,
)
from foragerr.logging import redact

logger = logging.getLogger("foragerr.http")

#: Maximum redirect hops the manual walk will follow (FRG-NFR-006).
MAX_REDIRECTS = 5

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

#: Request headers that carry credentials and MUST NOT cross to a redirect
#: host outside the original host (FRG-SEC-001).
SENSITIVE_HEADERS = frozenset(
    {"authorization", "proxy-authorization", "cookie", "x-api-key"}
)


@dataclass(frozen=True)
class FetchResult:
    """A fully-read, size-bounded response."""

    status_code: int
    headers: httpx.Headers
    content: bytes
    url: str  # final URL after any redirects


class StreamedResponse:
    """A streamed response handed to :meth:`OutboundClient.stream` callers.

    Exposes the final response's status, headers, and URL, and streams the body
    in chunks without buffering it. The factory does NOT cap the body here — the
    caller iterates :meth:`aiter_bytes` and enforces its own size bound
    (FRG-DDL-008 accounts bytes against the expected download size)."""

    def __init__(self, response: httpx.Response, url: httpx.URL) -> None:
        self._response = response
        self.status_code = response.status_code
        self.headers = response.headers
        self.url = str(url)

    async def aiter_bytes(self, chunk_size: int) -> AsyncIterator[bytes]:
        """Yield the response body in ``chunk_size`` byte chunks."""
        async for chunk in self._response.aiter_bytes(chunk_size):
            yield chunk


class OutboundClient:
    """An outbound HTTP client bound to one egress profile.

    Never construct directly — use :class:`HttpClientFactory`. Usable as an
    async context manager; call :meth:`aclose` otherwise.
    """

    def __init__(
        self,
        *,
        profile: str,
        validator: EgressValidator,
        timeout: httpx.Timeout,
        max_response_bytes: int,
        local_base: httpx.URL | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._profile = profile
        self._validator = validator
        self._local_base = local_base
        self._max_response_bytes = max_response_bytes
        self._client = httpx.AsyncClient(
            timeout=timeout,  # explicit connect/read/write/pool — never unlimited
            verify=True,  # always on; no opt-out parameter exists (FRG-NFR-006)
            follow_redirects=False,  # hops are walked manually below
            transport=transport,
            trust_env=False,  # no ambient proxy/CA surprises
        )

    @property
    def profile(self) -> str:
        return self._profile

    async def request(
        self,
        method: str,
        url: str | httpx.URL,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        content: bytes | str | None = None,
        max_bytes: int | None = None,
    ) -> FetchResult:
        """Issue a request with the manual, validated redirect walk.

        ``max_bytes`` may LOWER the response byte cap for this call; the
        configured cap is the ceiling. Raises
        :class:`~foragerr.http.errors.EgressPolicyError`,
        :class:`~foragerr.http.errors.TooManyRedirectsError`,
        :class:`~foragerr.http.errors.ResponseTooLargeError`, or the
        underlying ``httpx`` timeout/transport error.
        """
        cap = self._max_response_bytes
        if max_bytes is not None:
            cap = min(cap, max_bytes)
        response, final_url = await self._open_final(
            method, url, headers=headers, params=params, content=content
        )
        try:
            return await self._read_bounded(response, cap, final_url)
        finally:
            await response.aclose()

    @asynccontextmanager
    async def stream(
        self,
        method: str,
        url: str | httpx.URL,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        content: bytes | str | None = None,
        hop_check: "Callable[[httpx.URL], None] | None" = None,
    ) -> AsyncIterator["StreamedResponse"]:
        """Open a streamed response after the validated redirect walk.

        Unlike :meth:`request`, the body is NOT buffered or capped by the
        factory — the caller iterates :meth:`StreamedResponse.aiter_bytes` and
        enforces its own size bound (e.g. against an expected download size).
        Every guarantee of :meth:`request` still holds: each hop (including
        redirects) is egress-validated before connecting, TLS verification is
        always on, credentials are stripped when a hop leaves the original
        host, and the redirect chain is capped at :data:`MAX_REDIRECTS`.

        ``hop_check`` is an OPTIONAL per-hop validator (raising to refuse) run
        on every hop's URL in addition to the SSRF egress policy — the DDL
        downloader passes its per-provider scheme+host allowlist here so a
        scraped link's whole redirect chain is confined to allowed hosts
        (FRG-DDL-012).
        """
        response, final_url = await self._open_final(
            method, url, headers=headers, params=params, content=content,
            hop_check=hop_check,
        )
        try:
            yield StreamedResponse(response, final_url)
        finally:
            await response.aclose()

    async def _open_final(
        self,
        method: str,
        url: str | httpx.URL,
        *,
        headers: Mapping[str, str] | None,
        params: Mapping[str, Any] | None,
        content: bytes | str | None,
        hop_check: "Callable[[httpx.URL], None] | None" = None,
    ) -> tuple[httpx.Response, httpx.URL]:
        """Walk redirects (validating every hop) and return the OPEN final
        response plus its URL. Intermediate redirect responses are closed; the
        caller MUST close the returned response."""
        current = httpx.URL(url)
        if params:
            current = current.copy_merge_params(dict(params))
        original_host = (current.host or "").lower()
        send_method = method.upper()
        body = content

        for redirects_followed in range(MAX_REDIRECTS + 1):
            # Every hop, including hop 0, is validated BEFORE connecting.
            await self._validator.validate(
                current, profile=self._profile, local_base=self._local_base
            )
            if hop_check is not None:
                hop_check(current)  # per-provider allowlist (FRG-DDL-012)
            hop_headers = self._hop_headers(headers, current, original_host)
            request = self._client.build_request(
                send_method, current, headers=hop_headers, content=body
            )
            response = await self._client.send(request, stream=True)
            location = response.headers.get("location")
            if response.status_code in _REDIRECT_STATUSES and location:
                await response.aclose()  # redirect body discarded
                if redirects_followed == MAX_REDIRECTS:
                    message = (
                        f"stopped after {MAX_REDIRECTS} redirect hops "
                        f"(next would be {redact(str(current.join(location)))})"
                    )
                    logger.error(message)
                    raise TooManyRedirectsError(message)
                if response.status_code in (301, 302, 303) and send_method not in (
                    "GET",
                    "HEAD",
                ):
                    send_method, body = "GET", None
                current = current.join(location)
                continue
            return response, current
        raise AssertionError("unreachable")  # pragma: no cover

    async def get(self, url: str | httpx.URL, **kwargs: Any) -> FetchResult:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str | httpx.URL, **kwargs: Any) -> FetchResult:
        return await self.request("POST", url, **kwargs)

    def _hop_headers(
        self,
        headers: Mapping[str, str] | None,
        url: httpx.URL,
        original_host: str,
    ) -> httpx.Headers:
        """Caller headers for one hop; credentials are stripped when the hop
        host differs from the original request's host (FRG-SEC-001)."""
        hop = httpx.Headers(dict(headers) if headers else None)
        if (url.host or "").lower() != original_host:
            for name in SENSITIVE_HEADERS:
                if name in hop:
                    del hop[name]
        return hop

    async def _read_bounded(
        self, response: httpx.Response, cap: int, url: httpx.URL
    ) -> FetchResult:
        """Stream the body with a hard byte cap (FRG-NFR-006). Aborts oversize
        (or lying/absent Content-Length) reads; partial data is dropped."""
        declared = response.headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > cap:
            raise self._too_large(url, f"declared Content-Length {declared}", cap)
        received = 0
        chunks: list[bytes] = []
        async for chunk in response.aiter_bytes():
            received += len(chunk)
            if received > cap:
                # Bounded by construction: at most cap + one chunk was ever
                # held; it is discarded here, never returned to the caller.
                raise self._too_large(url, f"body exceeded {received - len(chunk)}+", cap)
            chunks.append(chunk)
        return FetchResult(
            status_code=response.status_code,
            headers=response.headers,
            content=b"".join(chunks),
            url=str(url),
        )

    def _too_large(self, url: httpx.URL, detail: str, cap: int) -> ResponseTooLargeError:
        message = (
            f"response from {redact(str(url))} aborted by byte cap "
            f"({detail} > cap {cap})"
        )
        logger.error(message)
        return ResponseTooLargeError(message)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "OutboundClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()


class HttpClientFactory:
    """Builds every outbound client foragerr uses (the FRG-NFR-006 choke
    point). Construct once from settings at startup:

    >>> factory = HttpClientFactory(settings)
    >>> cv = factory.external()                       # full egress policy
    >>> sab = factory.local_service("http://192.168.1.10:8080")

    ``resolver``, ``test_allow_addresses`` and ``transport`` are TEST-ONLY
    injection points (stub DNS records, allow fixture servers on 127.0.0.1,
    swap in ``httpx.MockTransport``); production wiring passes settings only.
    They cannot disable TLS verification, timeouts, redirect bounds, or the
    byte cap.
    """

    def __init__(
        self,
        settings: "Settings",
        *,
        resolver: Resolver | None = None,
        test_allow_addresses: Iterable[str] = (),
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._timeout = httpx.Timeout(
            connect=settings.http_connect_timeout_seconds,
            read=settings.http_read_timeout_seconds,
            write=settings.http_write_timeout_seconds,
            pool=settings.http_pool_timeout_seconds,
        )
        self._max_response_bytes = settings.http_max_response_bytes
        self._validator = EgressValidator(
            resolver=resolver, test_allow_addresses=test_allow_addresses
        )
        self._transport = transport

    def external(self) -> OutboundClient:
        """A client for hosts derived from external/config-supplied input;
        the full SSRF egress policy applies to every hop (FRG-SEC-001)."""
        return OutboundClient(
            profile=EXTERNAL,
            validator=self._validator,
            timeout=self._timeout,
            max_response_bytes=self._max_response_bytes,
            transport=self._transport,
        )

    def local_service(self, base_url: str | httpx.URL) -> OutboundClient:
        """A client for ONE operator-configured local integration.

        Requests matching ``base_url``'s origin (scheme + host + port) are
        allowed even on a private address; every other destination —
        including redirect hops leaving that origin — still gets the full
        external policy. Raises ``EgressPolicyError`` immediately for a
        malformed/forbidden-scheme base URL (config error, fail fast)."""
        base = httpx.URL(base_url)
        if base.scheme not in ALLOWED_SCHEMES or not base.host:
            safe = redact(str(base))
            message = (
                f"invalid local-service base URL {safe}: "
                "must be http(s) with a host"
            )
            logger.error(message)
            raise EgressPolicyError(message, url=safe, reason="invalid base URL")
        return OutboundClient(
            profile=LOCAL_SERVICE,
            validator=self._validator,
            timeout=self._timeout,
            max_response_bytes=self._max_response_bytes,
            local_base=base,
            transport=self._transport,
        )
