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


async def _drain_incoming(websocket: WebSocket) -> None:
    """Consume inbound frames only to observe the client closing the socket."""
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        return


async def ws_endpoint(websocket: WebSocket) -> None:
    broadcaster = websocket.app.state.ws_broadcaster
    await websocket.accept()
    conn = broadcaster.connect()
    pump_task = asyncio.ensure_future(pump(conn, websocket.send_text))
    recv_task = asyncio.ensure_future(_drain_incoming(websocket))
    try:
        # First to finish wins: pump returns on a slow-client drop; recv returns
        # on client disconnect. Either way we fall through to teardown.
        await asyncio.wait(
            {pump_task, recv_task}, return_when=asyncio.FIRST_COMPLETED
        )
    finally:
        broadcaster.disconnect(conn)
        for task in (pump_task, recv_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(pump_task, recv_task, return_exceptions=True)
        with contextlib.suppress(Exception):
            await websocket.close()


__all__ = ["ws_endpoint"]
