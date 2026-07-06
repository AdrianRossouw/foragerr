"""The ``/api/v1/ws`` WebSocket endpoint (FRG-API-010).

No auth in M1 (FRG-AUTH-001; Origin validation deferred to FRG-SEC-005/M3,
recorded as a residual risk): the endpoint accepts any connection. It holds no
server data — it just bridges the shared :class:`WsBroadcaster` on
``app.state.ws_broadcaster`` to one socket:

* :func:`pump` drains this socket's send queue to the wire;
* a read loop turns the (unused) inbound channel into a disconnect detector;

whichever finishes first tears the other down and closes the socket, so a
slow-client drop (pump returns) and a client disconnect (read returns) both
converge on the same cleanup.
"""

from __future__ import annotations

import asyncio
import contextlib

from fastapi import WebSocket, WebSocketDisconnect

from foragerr.ws.broadcast import pump


async def _drain_incoming(websocket: WebSocket) -> bool:
    """Consume inbound frames until the client closes the socket.

    Returns ``True`` when the client has disconnected (so the caller must not
    try to close an already-gone socket), ``False`` only if cancelled before
    that (the caller is tearing us down for another reason)."""
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        return True


async def ws_endpoint(websocket: WebSocket) -> None:
    broadcaster = websocket.app.state.ws_broadcaster
    # Register BEFORE accepting: the client considers itself connected the
    # moment the accept frame arrives, so registering afterwards leaves a
    # window where an event published by another task is broadcast to a
    # registry this socket isn't in yet and silently lost. Anything published
    # while we're still inside accept() just queues on the bounded connection
    # queue and is delivered once the pump starts.
    conn = broadcaster.connect()
    pump_task: asyncio.Future[None] | None = None
    recv_task: asyncio.Future[bool] | None = None
    try:
        await websocket.accept()
        pump_task = asyncio.ensure_future(pump(conn, websocket.send_text))
        recv_task = asyncio.ensure_future(_drain_incoming(websocket))
        # First to finish wins: pump returns on a slow-client drop; recv returns
        # on client disconnect. Either way we fall through to teardown.
        await asyncio.wait(
            {pump_task, recv_task}, return_when=asyncio.FIRST_COMPLETED
        )
    finally:
        broadcaster.disconnect(conn)
        # Did the CLIENT already disconnect? If so the socket is gone and
        # closing it again races the ASGI teardown — under the test portal that
        # surfaces as a CancelledError escaping this coroutine. Only WE close,
        # and only when the client is still connected (a slow-client pump drop).
        client_gone = bool(
            recv_task is not None
            and recv_task.done()
            and not recv_task.cancelled()
            and recv_task.result()
        )
        tasks = [t for t in (pump_task, recv_task) if t is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if not client_gone:
            # BaseException (incl. CancelledError from closing an already-torn-
            # down socket) must not escape endpoint teardown; a genuine
            # cancellation of this coroutine still lands at the awaits above.
            with contextlib.suppress(BaseException):
                await websocket.close()


__all__ = ["ws_endpoint"]
