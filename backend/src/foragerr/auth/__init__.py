"""foragerr authentication area (FRG-AUTH-002/003/004/010, FRG-SEC-005).

Mandatory single-user login behind a default-deny perimeter. The perimeter
itself is installed in the app factory as an app-level dependency
(``FastAPI(dependencies=[Depends(perimeter)])``) so it covers every mounted
router by construction; :func:`register_auth` wires the rest into the lifespan:

- maps the principal/session ORM models onto ``Base.metadata`` (bare import);
- registers the ``prune-sessions`` command + handler (bare import);
- mounts the login/logout/me/bootstrap-key router under ``/api/v1``;
- appends the env-bootstrap seeding startup hook (after the db area) and the
  session-prune task registration (after the scheduler area).
"""

from __future__ import annotations

from fastapi import FastAPI

# NB: do NOT re-export the ``perimeter`` function here — that name equals the
# ``foragerr.auth.perimeter`` submodule and would shadow it in the package
# namespace. Import the function from ``foragerr.auth.perimeter`` directly.
from foragerr.auth.perimeter import EXEMPT_PATHS

__all__ = ["EXEMPT_PATHS", "register_auth"]


def register_auth(app: FastAPI) -> None:
    """Wire the auth area into the app (auth extension point).

    The root perimeter dependency is installed at ``FastAPI(...)`` construction
    in ``create_app`` (it must exist before any router is included); this only
    mounts the auth routes and appends the seeding + prune-task hooks."""
    import foragerr.auth.models  # noqa: F401 — ORM model registration
    import foragerr.auth.commands  # noqa: F401 — command/handler registration
    from foragerr.auth.bootstrap import seed_principal_startup_hook
    from foragerr.auth.commands import register_prune_sessions_task
    from foragerr.auth.perimeter import OpdsVerifyCache
    from foragerr.auth.routes import router as auth_router

    # Per-app OPDS Basic verify-cache (FRG-AUTH-005): stashed on app.state (not a
    # module global) so concurrent test apps never share it; the perimeter reads
    # it and every credential write clears it.
    app.state.opds_verify_cache = OpdsVerifyCache()

    app.include_router(auth_router, prefix="/api/v1")

    # Seed the principal after the db area's engine/migration hook (app.state.db
    # live, principal table present) and before serving.
    app.state.startup_hooks.append(seed_principal_startup_hook)

    async def _register_prune_task(app: FastAPI) -> None:
        await register_prune_sessions_task(app.state.scheduler, app.state.settings)

    app.state.startup_hooks.append(_register_prune_task)
