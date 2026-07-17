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

_FORWARDED_SCHEMES = {"http", "https", "ws", "wss"}


def _parse_trusted(raw: str) -> frozenset[str]:
    """The comma-separated ``trusted_proxies`` setting as a peer-address set."""
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers") or ():
        if key == name:
            return value.decode("latin-1")
    return None


class TrustedProxyMiddleware:
    """Rewrite scheme/client from forwarded headers, trusted peers only (FRG-SEC-007)."""

    def __init__(self, app: ASGIApp, *, trusted_proxies: frozenset[str]) -> None:
        self.app = app
        self.trusted = trusted_proxies

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket") and self.trusted:
            client = scope.get("client")
            if client is not None and client[0] in self.trusted:
                self._resolve(scope)
        await self.app(scope, receive, send)

    def _resolve(self, scope: Scope) -> None:
        proto = _header(scope, b"x-forwarded-proto")
        if proto:
            # A chained proxy may send "https, http"; the first entry is the
            # client-facing hop, which is the one the Secure flag cares about.
            scheme = proto.split(",")[0].strip().lower()
            if scheme in _FORWARDED_SCHEMES:
                if scope["type"] == "websocket":
                    scheme = {"http": "ws", "https": "wss"}.get(scheme, scheme)
                scope["scheme"] = scheme
        forwarded_for = _header(scope, b"x-forwarded-for")
        if forwarded_for:
            # Rightmost entry not itself a trusted proxy = the real client as
            # seen by OUR proxy; anything left of it is client-controlled text.
            for entry in reversed(forwarded_for.split(",")):
                address = entry.strip().strip("[]")
                if address and address not in self.trusted:
                    scope["client"] = (address, 0)
                    break


class SecurityHeadersMiddleware:
    """Security headers on every response; unhandled errors become generic 500s."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        is_data = path == "/health" or path.startswith("/api/") or path.startswith("/opds")
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
    app.add_middleware(
        TrustedProxyMiddleware, trusted_proxies=_parse_trusted(settings.trusted_proxies)
    )
    app.add_middleware(SecurityHeadersMiddleware)
