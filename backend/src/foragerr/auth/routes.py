"""Login / logout / me / bootstrap-key + credential-lifecycle routes
(FRG-AUTH-002/004/005/006/007).

Mounted under ``/api/v1``. Only ``POST /api/v1/auth/login`` is on the perimeter
exempt list; everything else is authenticated like any other route (the
perimeter dependency runs first and stashes the resolved session on
``request.state``). The credential-lifecycle routes are unsafe methods, so the
perimeter's FRG-SEC-005 Origin check covers them on the cookie surface for free.

Every credential mutation re-authenticates the ADMIN password first. A wrong
current password always yields the SAME generic 403 (no field-specific oracle);
the refusal is logged structurally (the field, never any credential material).
"""

from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from foragerr.auth import sessions as sessions_mod
from foragerr.auth.audit import audit_event, client_ip
from foragerr.auth.models import PrincipalRow
from foragerr.auth.passwords import hash_password_async, verify_password_async
from foragerr.auth.perimeter import clear_opds_verify_cache, raise_throttled
from foragerr.auth.ratelimit import SURFACE_LOGIN
from foragerr.auth.repo import api_key_hash, get_principal
from foragerr.db.base import utcnow

router = APIRouter()

#: Upper bound on a submitted new password. Matches the login form's practical
#: ceiling — a value beyond this is a client bug or abuse, not a real credential.
MAX_PASSWORD_LENGTH = 1024


class LoginBody(BaseModel):
    username: str
    password: str
    remember: bool = False


class PasswordChangeBody(BaseModel):
    current_password: str
    new_password: str


class OpdsPasswordBody(BaseModel):
    #: ``current_password`` is the ADMIN password (re-auth), not the old OPDS one.
    current_password: str
    new_password: str


class ApiKeyRotateBody(BaseModel):
    current_password: str


def _set_session_cookie(
    response: Response, request: Request, token: str, tier: str, settings
) -> None:
    # `Secure` tracks the actual request scheme rather than being forced on:
    # the reference deployment runs plain HTTP inside a Tailscale tailnet (TLS
    # termination is DEP's story), so forcing Secure would silently drop the
    # cookie and lock the operator out. When a proxy terminates TLS the request
    # scheme is https and the flag is set. HttpOnly keeps JS from reading it;
    # SameSite=Lax is the CSRF baseline (FRG-SEC-005 adds the Origin check).
    response.set_cookie(
        key=sessions_mod.COOKIE_NAME,
        value=token,
        max_age=sessions_mod.tier_seconds(tier, settings),
        path="/",
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )


def _clear_session_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(
        key=sessions_mod.COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )


def _throttle_check(request: Request) -> None:
    """Refuse a throttled login before the KDF (FRG-AUTH-009), 429 + Retry-After.

    A no-op when no limiter is installed (a bare test app) or the key is not yet
    throttled. Runs at the top of the handler so a failure flood never reaches the
    constant-work scrypt path — the timing-uniformity discipline still holds for
    every non-throttled request."""
    limiter = getattr(request.app.state, "auth_rate_limiter", None)
    if limiter is None:
        return
    wait = limiter.retry_after(client_ip(request), SURFACE_LOGIN)
    if wait is not None:
        raise_throttled(wait)


def _record_login_failure(request: Request, username: str) -> None:
    """Count a credential failure and emit the audit events (FRG-AUTH-009)."""
    limiter = getattr(request.app.state, "auth_rate_limiter", None)
    if limiter is not None and limiter.record_failure(client_ip(request), SURFACE_LOGIN):
        audit_event("auth.backoff_triggered", request, SURFACE_LOGIN, level=logging.WARNING)
    audit_event(
        "auth.login.failure", request, SURFACE_LOGIN, level=logging.WARNING, username=username
    )


@router.post("/auth/login")
async def login(body: LoginBody, request: Request, response: Response) -> dict:
    """Establish a session for correct credentials; generic 401 otherwise.

    Runs exactly one KDF operation on every path (even unknown-user) so an
    attacker cannot distinguish "no such user" from "wrong password" by timing,
    and both yield the same generic failure. Repeated failures from one address
    are throttled before the KDF (FRG-AUTH-009); a success resets that key."""
    _throttle_check(request)
    db = request.app.state.db
    settings = request.app.state.settings
    principal = await get_principal(db)

    if principal is None:
        # constant work — no user-enumeration timing (off-loop, like verify)
        await hash_password_async(body.password)
        _record_login_failure(request, body.username)
        raise HTTPException(status_code=401, detail="invalid credentials")

    password_ok = await verify_password_async(body.password, principal.password_hash)
    if not (principal.username == body.username and password_ok):
        _record_login_failure(request, body.username)
        raise HTTPException(status_code=401, detail="invalid credentials")

    # Session-fixation defense (FRG-AUTH-004): regenerate the token. Any session
    # cookie the login request already carried is invalidated so a pre-login
    # (possibly attacker-fixed) token never survives authentication.
    presented = request.cookies.get(sessions_mod.COOKIE_NAME)
    if presented:
        await sessions_mod.logout(db, presented)

    tier = "remember" if body.remember else "session"
    token = await sessions_mod.create_session(
        db, principal.id, tier=tier, settings=settings
    )
    _set_session_cookie(response, request, token, tier, settings)
    limiter = getattr(request.app.state, "auth_rate_limiter", None)
    if limiter is not None:
        limiter.record_success(client_ip(request), SURFACE_LOGIN)
    audit_event("auth.login.success", request, SURFACE_LOGIN, username=principal.username)
    return {"username": principal.username}


@router.post("/auth/logout", status_code=204)
async def logout(request: Request, response: Response) -> Response:
    """Delete the acting session server-side and expire its cookie."""
    db = request.app.state.db
    token = getattr(request.state, "session_token", None)
    if token:
        await sessions_mod.logout(db, token)
    # Return the injected response so its Set-Cookie deletion header actually
    # ships — a freshly constructed Response would drop it (FastAPI only merges
    # the injected response's headers when the handler doesn't return its own).
    _clear_session_cookie(response, request)
    audit_event("auth.logout", request)
    response.status_code = 204
    return response


@router.get("/auth/me")
async def me(request: Request) -> dict:
    """The authenticated principal's username (perimeter guarantees a session)."""
    principal = await get_principal(request.app.state.db)
    if principal is None:  # pragma: no cover - perimeter already refused
        raise HTTPException(status_code=401, detail="authentication required")
    return {"username": principal.username}


@router.post("/auth/bootstrap-key")
async def bootstrap_key(request: Request) -> dict:
    """Return the seeded API key exactly ONCE (then 404; 404 after restart).

    Held in process memory only (never logged, never persisted plaintext); the
    first authenticated read consumes it. A tiny lifecycle affordance — the
    Settings UI for key display/rotation lands in a later change.

    POST, not GET: the read is state-changing (it consumes the key), so it must
    be an unsafe method that carries the FRG-SEC-005 CSRF Origin check — a GET
    would let a cross-site top-level navigation burn the operator's one-time
    retrieval under SameSite=Lax."""
    key = getattr(request.app.state, "bootstrap_api_key", None)
    if not key:
        raise HTTPException(
            status_code=404, detail="bootstrap key already retrieved or unavailable"
        )
    request.app.state.bootstrap_api_key = None
    return {"api_key": key}


# --- credential lifecycle (FRG-AUTH-005/006/007) -----------------------------


async def _reauth_admin(request: Request, current_password: str, *, field: str) -> PrincipalRow:
    """Re-authenticate the ADMIN password or raise a UNIFORM 403.

    Every credential mutation calls this first. The 403 body is identical
    regardless of which field/credential was being changed (no oracle), and the
    refusal is logged with the field name only — never any credential material.
    Returns the principal on success (the perimeter guarantees one exists)."""
    db = request.app.state.db
    principal = await get_principal(db)
    if principal is None:  # pragma: no cover - perimeter already refused
        raise HTTPException(status_code=403, detail="re-authentication failed")
    # Cap the re-auth input BEFORE the scrypt call: an oversized current_password
    # would otherwise inflate this request's memory-hard KDF cost (a real password
    # never approaches the cap). Same generic 403 as a wrong password — no oracle.
    if len(current_password) > MAX_PASSWORD_LENGTH or not await verify_password_async(
        current_password, principal.password_hash
    ):
        audit_event("auth.reauth_failed", request, level=logging.WARNING, field=field)
        raise HTTPException(status_code=403, detail="re-authentication failed")
    return principal


def _validate_new_password(candidate: str) -> None:
    """Reject an empty or absurdly long new password (422); never logs the value."""
    if not candidate:
        raise HTTPException(status_code=422, detail="new password must not be empty")
    if len(candidate) > MAX_PASSWORD_LENGTH:
        raise HTTPException(status_code=422, detail="new password is too long")


@router.post("/auth/password", status_code=204)
async def change_password(
    body: PasswordChangeBody, request: Request, response: Response
) -> Response:
    """Change the web login password (FRG-AUTH-004).

    Re-auths the current admin password, re-hashes the new one, and revokes every
    OTHER session (other devices, a lingering remember-me) while preserving the
    acting session — no self-logout on a routine rotation. Clears the OPDS
    verify-cache. Does NOT change the OPDS password, even when OPDS was seeded
    equal to the admin password: the two are independent credentials after
    seeding."""
    principal = await _reauth_admin(request, body.current_password, field="password")
    _validate_new_password(body.new_password)
    db = request.app.state.db
    new_hash = await hash_password_async(body.new_password)
    async with db.write_session() as session:
        row = await session.get(PrincipalRow, principal.id)
        row.password_hash = new_hash
        row.updated_at = utcnow()
    acting = getattr(request.state, "session_token", None)
    revoked = await sessions_mod.invalidate_others(db, principal.id, acting)
    clear_opds_verify_cache(request.app)
    audit_event("auth.password_changed", request, revoked_sessions=revoked)
    response.status_code = 204
    return response


@router.post("/auth/opds-password", status_code=204)
async def change_opds_password(
    body: OpdsPasswordBody, request: Request, response: Response
) -> Response:
    """Change the OPDS HTTP-Basic reader password (FRG-AUTH-005).

    Re-auths the ADMIN password (``current_password``), re-hashes the new OPDS
    password, and clears the verify-cache so a cached positive for the old
    password cannot linger. Leaves the env fingerprint untouched, so a stale
    FORAGERR_OPDS_PASSWORD does not clobber this on the next boot. Sessions are
    untouched (the OPDS password is not a session credential)."""
    principal = await _reauth_admin(request, body.current_password, field="opds_password")
    _validate_new_password(body.new_password)
    db = request.app.state.db
    new_hash = await hash_password_async(body.new_password)
    async with db.write_session() as session:
        row = await session.get(PrincipalRow, principal.id)
        row.opds_password_hash = new_hash
        row.updated_at = utcnow()
    clear_opds_verify_cache(request.app)
    audit_event("auth.opds_password_changed", request)
    response.status_code = 204
    return response


@router.post("/auth/api-key/rotate")
async def rotate_api_key(body: ApiKeyRotateBody, request: Request) -> dict:
    """Rotate the programmatic API key (FRG-AUTH-006/007).

    Re-auths the admin password, mints a fresh 256-bit key, stores only its
    SHA-256, and returns the raw key EXACTLY ONCE (never logged, never persisted
    plaintext). The old key stops authenticating immediately. Independent of the
    web password — a web password change never touches the key, and vice versa."""
    principal = await _reauth_admin(request, body.current_password, field="api_key")
    raw_key = secrets.token_urlsafe(32)
    db = request.app.state.db
    async with db.write_session() as session:
        row = await session.get(PrincipalRow, principal.id)
        row.api_key_sha256 = api_key_hash(raw_key)
        row.updated_at = utcnow()
    # Drop any never-retrieved bootstrap key: its hash is gone from the DB now, so
    # the one-shot handout would only ever return a dead key. Clearing it avoids
    # that confusing dangling affordance after a rotation.
    request.app.state.bootstrap_api_key = None
    # Reset the seen-source baseline so the rotated key re-audits its first use
    # from any address (FRG-AUTH-009).
    sources = getattr(request.app.state, "auth_apikey_sources", None)
    if sources is not None:
        sources.clear()
    audit_event("auth.apikey_rotated", request)
    return {"api_key": raw_key}


@router.post("/auth/logout-all", status_code=204)
async def logout_all(request: Request, response: Response) -> Response:
    """Revoke EVERY session including the acting one (FRG-AUTH-004).

    Deliberately requires no password: it grants nothing and only destroys
    access, so it is the shared-device / lost-device recovery an operator can
    reach even when they are unsure which sessions exist. The acting cookie is
    expired in the response like ``logout`` does."""
    db = request.app.state.db
    principal = await get_principal(db)
    if principal is not None:
        await sessions_mod.invalidate_all(db, principal.id)
    _clear_session_cookie(response, request)
    response.status_code = 204
    return response


@router.get("/auth/credentials")
async def credentials(request: Request) -> dict:
    """Non-secret credential status for the Settings screen (FRG-AUTH-006/007).

    Deliberately minimal: only the username. No secret, no derived flag that
    would cost a KDF or leak whether the OPDS password differs — the UI copy is
    static, and no extra persisted state is invented for it."""
    principal = await get_principal(request.app.state.db)
    if principal is None:  # pragma: no cover - perimeter already refused
        raise HTTPException(status_code=401, detail="authentication required")
    return {"username": principal.username}


__all__ = ["router"]
