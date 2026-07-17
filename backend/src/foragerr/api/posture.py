"""Deployment-posture perimeter middlewares (FRG-SEC-006, FRG-SEC-007, FRG-SEC-008).

Two pure-ASGI middlewares installed at the end of
:func:`foragerr.api.register_api`, so they sit OUTSIDE the request-limits
middleware (last added = outermost):

- :class:`TrustedProxyMiddleware` (FRG-SEC-007) — resolves the effective
  request scheme and client address ONCE, by rewriting ``scope["scheme"]`` and
  ``scope["client"]``, and only when the direct peer is on the operator's
  ``trusted_proxies`` list. Every downstream consumer — the session cookies'
  ``Secure`` flag (``request.url.scheme``), the FRG-NFR-014 rate-limiter key,
  and the ``auth.*`` audit ``client_ip`` (both ``scope["client"]``) — reads
  the rewritten scope, so no consumer ever re-derives values from raw
  forwarded headers and the three can never disagree. With the setting empty
  (the default) the scope is untouched: direct peer only, exactly the
  pre-M10 posture. Applies to the ``websocket`` scope too, so WS audit
  attribution matches HTTP.

- :class:`SecurityHeadersMiddleware` (FRG-SEC-006, FRG-SEC-008) — stamps the
  security response headers on EVERY http response (including the limits
  middleware's 413/429/431, perimeter 401s, and error-handler responses,
  which is why it must be outermost), and converts any unhandled exception
  into the uniform generic 500 envelope with the traceback going to the
  server-side log only. Catching here (rather than in Starlette's
  ServerErrorMiddleware, which sits outside all user middleware) is what
  guarantees even the 500 path carries the headers.

CSP is per-surface: API/OPDS/health responses are data, not documents, so
they carry the deny-everything policy; the SPA document gets a real
self-only policy. ``style-src 'unsafe-inline'`` is the one recorded
loosening — React styles elements via inline style attributes, which CSP
lumps under ``style-src`` (rationale in ``docs/security/posture.md``).
"""

from __future__ import annotations

import ipaddress
import json
import logging

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from foragerr.api.errors import error_body

logger = logging.getLogger("foragerr.api.posture")

__all__ = [
    "SecurityHeadersMiddleware",
    "TrustedProxyMiddleware",
    "install_posture",
]

#: Data surfaces (JSON/XML bodies): deny-everything document policy.
_CSP_DATA = "default-src 'none'; frame-ancestors 'none'"

#: The SPA document/asset policy: fully self-hosted, no external origins.
#: connect-src 'self' covers same-origin fetch AND the same-origin WebSocket
#: in current browsers; img/data+blob cover covers and client-side previews.
_CSP_SPA = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)

#: Header names this middleware owns (lower-case), stripped from any upstream
#: response before ours are appended so a header can never appear twice.
_OWNED = (b"content-security-policy", b"x-content-type-options", b"referrer-policy", b"x-frame-options")

#: X-Forwarded-Proto values accepted per scope type. ws/wss are not valid
#: forwarded protos for an HTTP request — accepting them there would silently
#: clear the cookie Secure decision on a misconfigured (but trusted) proxy.
_FORWARDED_SCHEMES = {
    "http": {"http", "https"},
    "websocket": {"http", "https", "ws", "wss"},
}


def _parse_trusted(raw: str) -> frozenset[str]:
    """The comma-separated ``trusted_proxies`` setting as a peer-address set.

    IP entries are canonicalized so they compare with normalized XFF
    candidates; a non-IP entry (a hostname peer — Docker service names, test
    clients) is kept verbatim and can only ever match the DIRECT peer, since
    wire candidates must parse as IPs.
    """
    return frozenset(
        _normalize_address(part) or part.strip() for part in raw.split(",") if part.strip()
    )


def _joined_header(scope: Scope, name: bytes) -> str:
    """ALL values for ``name``, comma-joined in field order (RFC 7230 §3.2.2).

    A proxy that emits its forwarded contribution as a SEPARATE header rather
    than appending must still end up rightmost — taking only the first header
    would hand the attacker-supplied duplicate the win.
    """
    return ", ".join(
        value.decode("latin-1") for key, value in scope.get("headers") or () if key == name
    )


def _normalize_address(entry: str) -> str | None:
    """One forwarded-for candidate as a canonical IP string, else ``None``.

    Handles ``[v6]``, ``[v6]:port``, and ``v4:port`` forms; anything that is
    not an IP literal after that is rejected — a malformed entry must never
    become a rate-limit key or an audit ``ip=`` field.
    """
    candidate = entry.strip()
    if not candidate:
        return None
    if candidate.startswith("["):
        host, _, rest = candidate[1:].partition("]")
        if rest not in ("",) and not rest.startswith(":"):
            return None
        candidate = host
    elif candidate.count(":") == 1:  # v4:port (a bare v6 has 2+ colons)
        candidate = candidate.partition(":")[0]
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


class TrustedProxyMiddleware:
    """Rewrite scheme/client from forwarded headers, trusted peers only (FRG-SEC-007)."""

    def __init__(self, app: ASGIApp, *, trusted_proxies: frozenset[str]) -> None:
        self.app = app
        self.trusted = trusted_proxies

    def _is_trusted(self, host: str) -> bool:
        # Direct peers and XFF entries match canonically when they parse as
        # IPs; a non-IP trusted entry (a hostname peer) matches verbatim.
        return host in self.trusted or (_normalize_address(host) or "") in self.trusted

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket") and self.trusted:
            client = scope.get("client")
            if client is not None and self._is_trusted(client[0]):
                self._resolve(scope)
        await self.app(scope, receive, send)

    def _resolve(self, scope: Scope) -> None:
        proto = _joined_header(scope, b"x-forwarded-proto")
        if proto:
            # The LAST entry is the nearest (trusted) hop's assertion — an
            # attacker-prepended entry or duplicate header never wins.
            scheme = proto.split(",")[-1].strip().lower()
            if scheme in _FORWARDED_SCHEMES[scope["type"]]:
                if scope["type"] == "websocket":
                    scheme = {"http": "ws", "https": "wss"}.get(scheme, scheme)
                scope["scheme"] = scheme
        forwarded_for = _joined_header(scope, b"x-forwarded-for")
        if forwarded_for:
            # Rightmost VALID entry not itself a trusted proxy = the real
            # client as seen by OUR proxy; anything left of it is
            # client-controlled text. An invalid entry fails CLOSED: stop
            # scanning and keep the direct peer — garbage must never leapfrog
            # into rate-limit keys or audit attribution.
            for entry in reversed(forwarded_for.split(",")):
                address = _normalize_address(entry)
                if address is None:
                    break
                if address not in self.trusted:
                    scope["client"] = (address, 0)
                    break


class SecurityHeadersMiddleware:
    """Security headers on every response; unhandled errors become generic 500s."""

    def __init__(self, app: ASGIApp, *, opds_base_path: str = "/opds") -> None:
        self.app = app
        self.opds_base = opds_base_path.rstrip("/") or "/opds"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        # Same boundary rule as the perimeter's _is_opds: exact segment match,
        # from the CONFIGURED base — a custom opds_base_path must not silently
        # demote OPDS feeds to the SPA policy, and /opdsx is not OPDS.
        is_data = (
            path == "/health"
            or path.startswith("/api/")
            or path == self.opds_base
            or path.startswith(self.opds_base + "/")
        )
        csp = _CSP_DATA if is_data else _CSP_SPA
        extra = [
            (b"content-security-policy", csp.encode("latin-1")),
            (b"x-content-type-options", b"nosniff"),
            (b"referrer-policy", b"same-origin"),
            (b"x-frame-options", b"DENY"),
        ]

        started = False

        async def send_with_headers(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                headers = [h for h in message.get("headers", []) if h[0].lower() not in _OWNED]
                headers.extend(extra)
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        except Exception:  # noqa: BLE001 - the last-resort disclosure boundary
            # FRG-SEC-008: the traceback goes to the structured log ONLY; the
            # client sees the uniform envelope with a generic message. If the
            # response already started we cannot replace it — re-raise and let
            # the server close the connection rather than emit a partial body.
            logger.exception("unhandled error serving %s %s", scope.get("method", "?"), path)
            if started:
                raise
            body = json.dumps(error_body("Internal server error")).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                        *extra,
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})


def install_posture(app) -> None:
    """Install both posture middlewares (called last in ``register_api``).

    ``add_middleware`` stacks outward: TrustedProxy is added first so the
    headers middleware ends up outermost (headers on every response, including
    anything the inner stack rejects), with TrustedProxy still outside the
    request-limits middleware (so the rate-limiter keys on the resolved
    client).
    """
    settings = app.state.settings
    app.add_middleware(TrustedProxyMiddleware, trusted_proxies=settings.trusted_proxy_set())
    app.add_middleware(SecurityHeadersMiddleware, opds_base_path=settings.opds_base_path)
