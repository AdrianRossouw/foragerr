"""WebSocket resource-change push area (FRG-API-010).

:func:`register_ws` is the app-factory extension point (mirrors
``register_api``/``register_scheduler``): it mounts ``/api/v1/ws`` and, at
startup, builds the :class:`WsBroadcaster` and subscribes it to the event bus
the scheduler area created on ``app.state.events``. It MUST be registered after
``register_scheduler`` so its startup hook runs after the bus exists.
"""

from __future__ import annotations

from fastapi import FastAPI

from foragerr.ws.broadcast import WsBroadcaster

__all__ = ["WsBroadcaster", "register_ws"]


def register_ws(app: FastAPI) -> None:
    from foragerr.ws.router import ws_endpoint

    # Registered directly with the full path rather than via
    # ``include_router(prefix="/api/v1")``: in this FastAPI version a websocket
    # route nested under an included router resolves to an EMPTY path in the
    # route-context walk (``iter_route_contexts``), tripping the "every route is
    # under /api/v1" invariant. Adding it directly gives it its real path.
    app.add_api_websocket_route("/api/v1/ws", ws_endpoint)

    async def _startup(app: FastAPI) -> None:
        broadcaster = WsBroadcaster()
        broadcaster.subscribe(app.state.events)
        app.state.ws_broadcaster = broadcaster

    async def _shutdown(app: FastAPI) -> None:
        broadcaster = getattr(app.state, "ws_broadcaster", None)
        if broadcaster is not None:
            broadcaster.unsubscribe()

    app.state.startup_hooks.append(_startup)
    app.state.shutdown_hooks.append(_shutdown)
