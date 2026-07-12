"""Default-deny auth perimeter over every surface (FRG-AUTH-010, FRG-SEC-005).

A SINGLE dependency installed at the application root (``FastAPI(dependencies=
[Depends(perimeter)])`` in the app factory) covers every mounted API/OPDS
router by construction — routes are born protected; the only escape is the
explicit, centralized :data:`EXEMPT_PATHS`. A newly mounted router is refused
with zero extra thought (proven by the route-inventory test). The static SPA
mount is a Starlette ``Mount``, which app-level dependencies do not touch, so it
serves the unauthenticated shell (static UI code only; every data call it makes
is authenticated).

Accepted credentials by surface:

- **session cookie** (``foragerr_session``, a live unexpired row) — anywhere;
- **``X-Api-Key`` header** (SHA-256 match) — anywhere; NEVER a query parameter;
- **HTTP Basic** against the OPDS password — only on the ``/opds`` subtree,
  where a bare request is answered 401 with a ``Basic`` realm challenge.

CSRF (FRG-SEC-005): an unsafe-method request authenticated by COOKIE must carry
an Origin (or Referer) matching the deployment's own origin or a configured
extra origin — foreign or absent Origin is refused 403 before the handler. The
API-key surface is CSRF-immune by construction (a browser cannot attach the
header cross-site), so it skips the check.

The WebSocket handshake runs the same credential check plus the Origin
allowlist and refuses pre-upgrade (see :mod:`foragerr.ws.router`).
"""

from __future__ import annotations

import base64
import binascii
import hmac
import logging

from fastapi import HTTPException
from starlette.requests import HTTPConnection

from foragerr.auth import sessions as sessions_mod
from foragerr.auth.repo import find_by_api_key, get_principal
from foragerr.auth.passwords import verify_password_async

logger = logging.getLogger("foragerr.auth")

#: The EXACT, centralized exempt list (FRG-AUTH-010). Everything else is
#: default-deny. The static SPA shell/assets are a ``Mount`` (not reached by the
#: app-level dependency), so they are exempt by construction and not listed here
#: — every API call the shell makes is still authenticated.
EXEMPT_PATHS = frozenset(
    {
        "/health",  # DEP liveness probe, credential-free by contract
        "/api/v1/auth/login",  # the one door through the perimeter
    }
)

OPDS_REALM = 'Basic realm="foragerr-opds"'

#: HTTP methods that never change state — exempt from the CSRF Origin check.
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def is_exempt(path: str) -> bool:
    """True iff ``path`` is on the fixed exempt list (exact match)."""
    return path in EXEMPT_PATHS


def _is_opds(path: str, opds_base: str) -> bool:
    return path == opds_base or path.startswith(opds_base + "/")


def _own_origins(host: str | None, scheme: str) -> set[str]:
    """The deployment's own origin(s) derived from the request host.

    Both schemes are accepted for the host: TLS termination is DEP's story and a
    reverse proxy may present https upstream while the app sees http, so pinning
    the scheme would wrongly reject a legitimate same-host request."""
    if not host:
        return set()
    return {f"http://{host}", f"https://{host}"}


def allowed_origins(request_host: str | None, scheme: str, settings) -> set[str]:
    """Own origin(s) plus any configured extra origins (reverse-proxy setups)."""
    return _own_origins(request_host, scheme) | settings.auth_extra_origins()


def _decode_basic(header: str) -> tuple[str, str] | None:
    if not header.lower().startswith("basic "):
        return None
    try:
        raw = base64.b64decode(header.split(" ", 1)[1].strip()).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    if ":" not in raw:
        return None
    user, password = raw.split(":", 1)
    return user, password


async def _authenticate(request: HTTPConnection) -> tuple[int, str] | None:
    """Resolve a request to ``(principal_id, auth_via)`` or ``None``.

    ``auth_via`` is one of ``cookie`` / ``api_key`` / ``basic``. Tried in order;
    a query-parameter API key is never consulted."""
    app = request.app
    db = app.state.db
    settings = app.state.settings

    # 1. Session cookie (any surface).
    token = request.cookies.get(sessions_mod.COOKIE_NAME)
    if token:
        authed = await sessions_mod.authenticate(db, token, settings=settings)
        if authed is not None:
            request.state.session_token = token
            return authed.principal_id, "cookie"

    # 2. X-Api-Key header (any surface). Header only — never a query param.
    api_key = request.headers.get("x-api-key")
    if api_key:
        principal = await find_by_api_key(db, api_key)
        if principal is not None:
            return principal.id, "api_key"

    # 3. OPDS HTTP Basic — only on the /opds subtree. The username binds to the
    #    principal (readers are configured with the admin username, manual
    #    authentication.md); the password KDF runs on every attempt so a wrong
    #    username is indistinguishable from a wrong password.
    if _is_opds(request.scope["path"], settings.opds_base_path):
        creds = _decode_basic(request.headers.get("authorization", ""))
        if creds is not None:
            principal = await get_principal(db)
            if principal is not None:
                user_ok = hmac.compare_digest(
                    creds[0].encode("utf-8"), principal.username.encode("utf-8")
                )
                password_ok = await verify_password_async(
                    creds[1], principal.opds_password_hash
                )
                if user_ok and password_ok:
                    return principal.id, "basic"

    return None


def _csrf_ok(request: HTTPConnection, settings) -> bool:
    """Origin/Referer check for a cookie-authed unsafe method (FRG-SEC-005)."""
    origin = request.headers.get("origin")
    allowed = allowed_origins(
        request.headers.get("host"), request.url.scheme, settings
    )
    if origin is not None:
        return origin in allowed
    # No Origin: fall back to Referer's origin; absent both, refuse (an unsafe
    # cookie-authed request we cannot attribute to our own origin is treated as
    # forged).
    referer = request.headers.get("referer")
    if not referer:
        return False
    from urllib.parse import urlsplit

    parts = urlsplit(referer)
    if not parts.scheme or not parts.netloc:
        return False
    return f"{parts.scheme}://{parts.netloc}" in allowed


async def perimeter(conn: HTTPConnection) -> None:
    """The root default-deny dependency (FRG-AUTH-010).

    Installed at the app root, so FastAPI applies it to HTTP *and* WebSocket
    routes. The WebSocket handshake is authenticated in the endpoint itself
    (pre-accept, with its own Origin rule — :mod:`foragerr.ws.router`), so this
    dependency no-ops on the websocket scope and enforces only the HTTP
    surfaces here. ``HTTPConnection`` (the shared base of ``Request`` and
    ``WebSocket``) is used so a single dependency binds to both scopes.

    Exempt paths pass through; every other HTTP route requires a valid
    credential. A cookie-authenticated unsafe method additionally passes the
    CSRF Origin check (FRG-SEC-005). Failures raise 401 (OPDS adds its Basic
    challenge) or 403 (CSRF) through the uniform error handler."""
    if conn.scope["type"] != "http":
        return  # websocket: enforced in the endpoint handshake (pre-upgrade)

    path = conn.scope["path"]
    if is_exempt(path):
        return

    settings = conn.app.state.settings
    resolved = await _authenticate(conn)
    if resolved is None:
        if _is_opds(path, settings.opds_base_path):
            raise HTTPException(
                status_code=401,
                detail="authentication required",
                headers={"WWW-Authenticate": OPDS_REALM},
            )
        raise HTTPException(status_code=401, detail="authentication required")

    principal_id, auth_via = resolved
    conn.state.principal_id = principal_id
    conn.state.auth_via = auth_via

    # CSRF: only the cookie surface is browser-ambient; the API-key surface is
    # immune by construction (the header cannot be attached cross-site).
    if auth_via == "cookie" and conn.scope["method"] not in _SAFE_METHODS:
        if not _csrf_ok(conn, settings):
            raise HTTPException(
                status_code=403, detail="cross-site request blocked"
            )


def ws_origin_ok(websocket, settings) -> bool:
    """WebSocket Origin allowlist check (FRG-SEC-005).

    A browser always sends Origin on a WS handshake, so a foreign Origin is a
    cross-site socket and is refused. An ABSENT Origin is a non-browser client
    (a native reader, the test harness) that cannot be a CSWSH vector, so it is
    allowed once its credential checks out."""
    origin = websocket.headers.get("origin")
    if origin is None:
        return True
    allowed = allowed_origins(
        websocket.headers.get("host"), websocket.url.scheme, settings
    )
    return origin in allowed


async def authenticate_ws(websocket) -> int | None:
    """Resolve a WS handshake to a principal id via cookie or ``X-Api-Key``.

    HTTP Basic is not offered on the socket (it is the OPDS realm only). Returns
    ``None`` when no valid credential is present."""
    app = websocket.app
    db = app.state.db
    settings = app.state.settings

    token = websocket.cookies.get(sessions_mod.COOKIE_NAME)
    if token:
        authed = await sessions_mod.authenticate(db, token, settings=settings)
        if authed is not None:
            return authed.principal_id

    api_key = websocket.headers.get("x-api-key")
    if api_key:
        principal = await find_by_api_key(db, api_key)
        if principal is not None:
            return principal.id
    return None


__all__ = [
    "EXEMPT_PATHS",
    "OPDS_REALM",
    "allowed_origins",
    "authenticate_ws",
    "is_exempt",
    "perimeter",
    "ws_origin_ok",
]
