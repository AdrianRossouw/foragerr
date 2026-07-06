"""Serve the built React SPA statically from the FastAPI app (FRG-DEP-001).

The multi-stage Docker image builds ``frontend/`` in a node stage and copies the
resulting ``dist/`` into the runtime image. FastAPI then serves that static bundle
at ``/`` so a single container answers the SPA, the API (``/api``), the OPDS catalog
(``/opds``) and the health probe (``/health``) on one port.

Design notes
------------
- **Mounted last, at ``/``.** Starlette matches routes in registration order, so the
  API / OPDS / health routers registered earlier in ``create_app`` always win; only
  paths they do not claim fall through to this mount. It therefore cannot shadow any
  application route.
- **Client-side routing.** React-router owns paths like ``/series/5`` that have no
  file on disk. :class:`_SPAStaticFiles` falls back to ``index.html`` on a 404 so a
  hard refresh or deep link renders the SPA rather than a bare 404 — the standard
  history-API-fallback contract. A genuinely missing *asset* (a request that already
  carries a file extension) still 404s so broken bundles are visible.
- **Gated on the bundle existing.** Running from source (no build) or in the test
  suite, the dist dir is absent and ``register_spa`` is a no-op — the API-only app is
  unchanged. ``create_app`` stays importable without a frontend build.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

logger = logging.getLogger("foragerr.spa")

#: Where the Docker image drops the built frontend. Overridable via
#: ``FORAGERR_STATIC_DIR`` for non-container layouts; unset + absent dir = no SPA.
STATIC_DIR_ENV = "FORAGERR_STATIC_DIR"
DEFAULT_STATIC_DIR = Path("/app/static")


def resolve_static_dir() -> Path:
    """The directory the built SPA is served from (env override wins)."""
    return Path(os.environ.get(STATIC_DIR_ENV, str(DEFAULT_STATIC_DIR))).expanduser()


class _SPAStaticFiles(StaticFiles):
    """StaticFiles with history-API fallback to ``index.html`` for SPA routes."""

    def __init__(self, *args, reserved_prefixes: tuple[str, ...] = (), **kwargs) -> None:
        super().__init__(*args, **kwargs)
        #: Backend mount prefixes (``/api``, ``/opds``, ``/health``) whose
        #: unrouted paths must NOT masquerade as the SPA shell — a mistyped
        #: ``/api/v1/...`` or ``/opds/...`` must keep its real 404 so the
        #: JSON/Atom error contract holds, not answer 200 HTML.
        self._reserved = tuple(reserved_prefixes)

    def _is_reserved(self, path: str) -> bool:
        # ``path`` is the request path with the "/" mount prefix stripped
        # (e.g. "api/v1/x"); compare in leading-slash form against the prefixes.
        normalized = "/" + path.lstrip("/")
        return any(
            normalized == prefix or normalized.startswith(prefix + "/")
            for prefix in self._reserved
        )

    async def get_response(self, path: str, scope: Scope):
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            # Only a *route* miss falls back to the shell. A missing asset (the
            # request path already has a file suffix, e.g. a stale hashed bundle)
            # keeps its 404 so a broken deploy is not silently masked as the SPA.
            # A path under a reserved backend prefix also keeps its 404 so an
            # unrouted /api or /opds request never answers 200 HTML.
            if (
                exc.status_code == 404
                and not Path(path).suffix
                and not self._is_reserved(path)
            ):
                return await super().get_response("index.html", scope)
            raise


def register_spa(app: FastAPI, dist_dir: Path | None = None) -> bool:
    """Mount the built SPA at ``/`` if the bundle is present.

    Returns ``True`` when the SPA was mounted, ``False`` when the dist dir (or its
    ``index.html``) is absent — the API-only app then behaves exactly as before.
    Call once per app during ``create_app`` (additive, after the API/OPDS/health
    routers); the no-build no-op keeps the factory importable without a frontend.
    """
    dist_dir = dist_dir or resolve_static_dir()
    index = dist_dir / "index.html"
    if not index.is_file():
        logger.info("SPA bundle not found at %s; serving API only", dist_dir)
        return False
    # Reserved backend prefixes never fall back to the SPA shell (see
    # ``_SPAStaticFiles``). The OPDS base is configurable, so read it from the
    # app's settings when present (a bare test app may have none — default to
    # the documented "/opds").
    settings = getattr(app.state, "settings", None)
    opds_base = getattr(settings, "opds_base_path", "/opds")
    reserved = ("/api", "/health", opds_base)
    app.mount(
        "/",
        _SPAStaticFiles(directory=str(dist_dir), html=True, reserved_prefixes=reserved),
        name="spa",
    )
    logger.info("serving SPA from %s", dist_dir)
    return True
