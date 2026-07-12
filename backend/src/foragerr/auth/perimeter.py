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
import hashlib
import hmac
import logging
import math
import time
from collections import OrderedDict
from typing import Callable

from fastapi import HTTPException
from starlette.requests import HTTPConnection

from foragerr.auth import sessions as sessions_mod
from foragerr.auth.audit import audit_event
from foragerr.auth.ratelimit import SURFACE_API_KEY, SURFACE_BASIC
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

#: OPDS verify-cache tuning (FRG-AUTH-005). A reader (Panels, KyBook, …) fires a
#: burst of OPDS requests each carrying the same Basic header; without a cache
#: every one pays a full scrypt verify (~170 ms) and one reader can head-of-line
#: block the pool. The window is short and the capacity tiny — it is a burst
#: absorber, not a session store.
OPDS_VERIFY_TTL_SECONDS = 60.0
OPDS_VERIFY_CAPACITY = 8


class OpdsVerifyCache:
    """In-process, positive-only TTL cache of OPDS Basic verifications.

    Key is the SHA-256 of the PRESENTED ``username\\0password`` (so a wrong
    username can never share a slot with the real one, and the raw password is
    never held); value is the resolved principal id. Only SUCCESSFUL verifies
    are ever stored — a failed attempt is never cached, so the KDF always runs
    for wrong credentials (no oracle, no bypass). Entries expire after
    :data:`OPDS_VERIFY_TTL_SECONDS`; capacity is bounded at
    :data:`OPDS_VERIFY_CAPACITY` with oldest-first eviction.

    Lives on ``app.state`` (per-app, not module-global) so tests stay isolated;
    ``clock`` is injectable like :class:`foragerr.indexers.caps.CapsCache`. Any
    principal credential write (in-app change or env re-seed) calls
    :meth:`clear` so a rotated password can never be authenticated from a stale
    positive entry.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = OPDS_VERIFY_TTL_SECONDS,
        capacity: int = OPDS_VERIFY_CAPACITY,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._capacity = capacity
        self._clock = clock
        self._entries: OrderedDict[bytes, tuple[int, float]] = OrderedDict()
        #: Bumped on every clear(). A verify that begins under one generation and
        #: finishes after a clear (the KDF awaits, so a credential write can land
        #: mid-verify) must NOT write its now-stale positive — put() rejects it.
        self._generation = 0

    @staticmethod
    def _key(username: str, password: str) -> bytes:
        # Length-unambiguous: hash each field, then hash the two digests. A plain
        # ``user + NUL + password`` join is ambiguous in principle (("a\0b","c")
        # and ("a","b\0c") collide); env/login inputs cannot contain NUL so it is
        # not exploitable today, but the fixed-width digest join removes the class
        # entirely (defense-in-depth, gate finding).
        u = hashlib.sha256(username.encode("utf-8")).digest()
        p = hashlib.sha256(password.encode("utf-8")).digest()
        return hashlib.sha256(u + p).digest()

    def generation(self) -> int:
        """The current clear-generation. Capture BEFORE reading the credential a
        verify will validate, then pass it to :meth:`put`."""
        return self._generation

    def get(self, username: str, password: str) -> int | None:
        """The cached principal id for these exact creds if still fresh, else None."""
        key = self._key(username, password)
        entry = self._entries.get(key)
        if entry is None:
            return None
        principal_id, expires_at = entry
        if self._clock() >= expires_at:
            del self._entries[key]
            return None
        return principal_id

    def put(
        self, username: str, password: str, principal_id: int, *, generation: int
    ) -> None:
        """Cache a SUCCESSFUL verify (never call this for a failed one).

        ``generation`` is the value :meth:`generation` returned before the verify
        read its credentials; if a :meth:`clear` has intervened since, the write
        is dropped — the positive is stale (the credential may have just been
        rotated) and must not be resurrected into the freshly-cleared cache."""
        if generation != self._generation:
            return
        key = self._key(username, password)
        self._entries[key] = (principal_id, self._clock() + self._ttl)
        self._entries.move_to_end(key)
        while len(self._entries) > self._capacity:
            self._entries.popitem(last=False)  # drop oldest

    def clear(self) -> None:
        """Drop every entry and advance the generation — called on any principal
        credential write, so an in-flight verify cannot re-seed a stale positive."""
        self._generation += 1
        self._entries.clear()


def clear_opds_verify_cache(app) -> None:
    """Clear the app's OPDS verify-cache if one is installed (no-op otherwise).

    The single choke point the bootstrap re-seed and the credential-lifecycle
    routes call after any password write (FRG-AUTH-005)."""
    cache = getattr(app.state, "opds_verify_cache", None)
    if cache is not None:
        cache.clear()


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


def _client_ip(request: HTTPConnection) -> str:
    """The direct-connection client IP (``X-Forwarded-For`` is not trusted)."""
    client = request.client
    return client.host if client is not None else "unknown"


def _raise_throttled(wait: float) -> None:
    """Refuse a throttled surface with 429 + ``Retry-After`` (FRG-AUTH-009)."""
    raise HTTPException(
        status_code=429,
        detail="too many failed attempts",
        headers={"Retry-After": str(int(math.ceil(wait)))},
    )


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

    limiter = getattr(app.state, "auth_rate_limiter", None)
    ip = _client_ip(request)

    # 2. X-Api-Key header (any surface). Header only — never a query param. A
    #    PRESENT key is a credential-bearing attempt: the surface is throttled
    #    before the lookup and a mismatch counts toward backoff (FRG-AUTH-009).
    api_key = request.headers.get("x-api-key")
    if api_key:
        if limiter is not None:
            wait = limiter.retry_after(ip, SURFACE_API_KEY)
            if wait is not None:
                _raise_throttled(wait)
        principal = await find_by_api_key(db, api_key)
        if principal is not None:
            if limiter is not None:
                limiter.record_success(ip, SURFACE_API_KEY)
            # Audit a successful key use once per source per window (never per
            # request) so a leaked key used from a new address surfaces without
            # flooding the log (FRG-AUTH-009).
            sources = getattr(app.state, "auth_apikey_sources", None)
            if sources is not None and sources.observe(ip):
                audit_event("auth.apikey_source_seen", request, SURFACE_API_KEY)
            return principal.id, "api_key"
        if limiter is not None and limiter.record_failure(ip, SURFACE_API_KEY):
            audit_event(
                "auth.backoff_triggered", request, SURFACE_API_KEY, level=logging.WARNING
            )
        audit_event("auth.apikey_failure", request, SURFACE_API_KEY, level=logging.WARNING)

    # 3. OPDS HTTP Basic — only on the /opds subtree. The username binds to the
    #    principal (readers are configured with the admin username, manual
    #    authentication.md); the password KDF runs on every attempt so a wrong
    #    username is indistinguishable from a wrong password.
    if _is_opds(request.scope["path"], settings.opds_base_path):
        creds = _decode_basic(request.headers.get("authorization", ""))
        if creds is not None:
            # Throttle a decodable-but-failing Basic key BEFORE the cache/KDF, and
            # return the 429 (not the realm challenge) so a looping reader surfaces
            # the error instead of re-prompting forever (FRG-AUTH-009).
            if limiter is not None:
                wait = limiter.retry_after(ip, SURFACE_BASIC)
                if wait is not None:
                    _raise_throttled(wait)
            cache = getattr(app.state, "opds_verify_cache", None)
            generation = 0
            if cache is not None:
                # Capture the generation BEFORE reading the principal, so a
                # credential write (clear) landing during the KDF below causes the
                # eventual put() to be dropped rather than resurrect a stale
                # positive (TOCTOU gate finding).
                generation = cache.generation()
                cached_id = cache.get(creds[0], creds[1])
                if cached_id is not None:
                    # A prior verify of these EXACT creds succeeded within the
                    # TTL — skip the scrypt round-trip (only positives are ever
                    # cached, so this can never accept a wrong password). A cache
                    # hit is a success, so it resets the key; the success is NOT
                    # re-logged (opds success is logged per verification only).
                    if limiter is not None:
                        limiter.record_success(ip, SURFACE_BASIC)
                    return cached_id, "basic"
            principal = await get_principal(db)
            if principal is not None:
                # On a cache miss both checks always run (the KDF fires even for
                # a wrong username), so a bad username stays timing-indistinct
                # from a bad password.
                user_ok = hmac.compare_digest(
                    creds[0].encode("utf-8"), principal.username.encode("utf-8")
                )
                password_ok = await verify_password_async(
                    creds[1], principal.opds_password_hash
                )
                if user_ok and password_ok:
                    if cache is not None:
                        cache.put(
                            creds[0], creds[1], principal.id, generation=generation
                        )
                    if limiter is not None:
                        limiter.record_success(ip, SURFACE_BASIC)
                    # OPDS success is logged per VERIFICATION (this cache-fill
                    # path), never per request — a reader polling with valid creds
                    # cannot flood the log.
                    audit_event("auth.opds_success", request, SURFACE_BASIC)
                    return principal.id, "basic"
            # Decodable Basic that did not verify — a credential-bearing failure.
            if limiter is not None and limiter.record_failure(ip, SURFACE_BASIC):
                audit_event(
                    "auth.backoff_triggered", request, SURFACE_BASIC, level=logging.WARNING
                )
            audit_event("auth.opds_failure", request, SURFACE_BASIC, level=logging.WARNING)

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
    "OpdsVerifyCache",
    "allowed_origins",
    "authenticate_ws",
    "clear_opds_verify_cache",
    "is_exempt",
    "perimeter",
    "ws_origin_ok",
]
