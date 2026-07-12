"""Login / logout / me / bootstrap-key routes (FRG-AUTH-002/004).

Mounted under ``/api/v1``. Only ``POST /api/v1/auth/login`` is on the perimeter
exempt list; ``logout`` / ``me`` / ``bootstrap-key`` are authenticated like any
other route (the perimeter dependency runs first and stashes the resolved
session on ``request.state``).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from foragerr.auth import sessions as sessions_mod
from foragerr.auth.passwords import hash_password, verify_password
from foragerr.auth.repo import get_principal

logger = logging.getLogger("foragerr.auth")

router = APIRouter()


class LoginBody(BaseModel):
    username: str
    password: str
    remember: bool = False


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


@router.post("/auth/login")
async def login(body: LoginBody, request: Request, response: Response) -> dict:
    """Establish a session for correct credentials; generic 401 otherwise.

    Runs exactly one KDF operation on every path (even unknown-user) so an
    attacker cannot distinguish "no such user" from "wrong password" by timing,
    and both yield the same generic failure."""
    db = request.app.state.db
    settings = request.app.state.settings
    principal = await get_principal(db)

    if principal is None:
        hash_password(body.password)  # constant work — no user-enumeration timing
        raise HTTPException(status_code=401, detail="invalid credentials")

    password_ok = verify_password(body.password, principal.password_hash)
    if not (principal.username == body.username and password_ok):
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
    return {"username": principal.username}


@router.post("/auth/logout", status_code=204)
async def logout(request: Request, response: Response) -> Response:
    """Delete the acting session server-side and expire its cookie."""
    db = request.app.state.db
    token = getattr(request.state, "session_token", None)
    if token:
        await sessions_mod.logout(db, token)
    _clear_session_cookie(response, request)
    return Response(status_code=204)


@router.get("/auth/me")
async def me(request: Request) -> dict:
    """The authenticated principal's username (perimeter guarantees a session)."""
    principal = await get_principal(request.app.state.db)
    if principal is None:  # pragma: no cover - perimeter already refused
        raise HTTPException(status_code=401, detail="authentication required")
    return {"username": principal.username}


@router.get("/auth/bootstrap-key")
async def bootstrap_key(request: Request) -> dict:
    """Return the seeded API key exactly ONCE (then 404; 404 after restart).

    Held in process memory only (never logged, never persisted plaintext); the
    first authenticated read consumes it. A tiny lifecycle affordance — the
    Settings UI for key display/rotation lands in a later change."""
    key = getattr(request.app.state, "bootstrap_api_key", None)
    if not key:
        raise HTTPException(
            status_code=404, detail="bootstrap key already retrieved or unavailable"
        )
    request.app.state.bootstrap_api_key = None
    return {"api_key": key}


__all__ = ["router"]
