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
import logging
import time
from collections import deque

from fastapi import WebSocket, WebSocketDisconnect

from foragerr.ws.broadcast import pump

logger = logging.getLogger("foragerr.ws")


async def _drain_incoming(
    websocket: WebSocket,
    *,
    max_bytes: int,
    max_messages_per_second: int,
) -> bool:
    """Consume inbound frames until the client closes or violates a limit.

    The WebSocket is server-push; this inbound channel exists only as a
    disconnect detector, so any real inbound payload is anomalous. Two limits
    bound it (FRG-NFR-014): an inbound frame larger than ``max_bytes``, or a
    sustained burst exceeding ``max_messages_per_second`` (sliding 1-second
    window), is logged once and ends the loop.

    Returns ``True`` when the CLIENT disconnected (the socket is gone, so the
    caller must not close it again — the ``0e0456a`` client-gone guard), and
    ``False`` otherwise: either cancelled by the caller's teardown, or a limit
    violation where the socket is still connected so the endpoint's existing
    ``if not client_gone: await websocket.close()`` performs the single close.
    """
    arrivals: deque[float] = deque()
    try:
        while True:
            text = await websocket.receive_text()
            if len(text.encode("utf-8")) > max_bytes:
                logger.warning(
                    "ws: closing client — inbound frame over the %d-byte cap",
                    max_bytes,
                )
                return False  # client still connected: endpoint closes once
            now = time.monotonic()
            arrivals.append(now)
            cutoff = now - 1.0
            while arrivals and arrivals[0] < cutoff:
                arrivals.popleft()
            if len(arrivals) > max_messages_per_second:
                logger.warning(
                    "ws: closing client — inbound rate over %d msgs/s",
                    max_messages_per_second,
                )
                return False  # client still connected: endpoint closes once
    except WebSocketDisconnect:
        return True


async def ws_endpoint(websocket: WebSocket) -> None:
    broadcaster = websocket.app.state.ws_broadcaster
    settings = websocket.app.state.settings
    # Concurrent-connection cap (FRG-NFR-014): refuse over-cap sockets BEFORE
    # accept() and WITHOUT registering, so the registry and every live socket
    # are untouched. 1013 = Try Again Later — a clean handshake refusal. Below
    # the cap try_connect registers exactly as connect() did, so the
    # register-before-accept ordering for accepted sockets is preserved.
    conn = broadcaster.try_connect()
    if conn is None:
        with contextlib.suppress(BaseException):
            await websocket.close(code=1013)
        return
    # Register BEFORE accepting: the client considers itself connected the
    # moment the accept frame arrives, so registering afterwards leaves a
    # window where an event published by another task is broadcast to a
    # registry this socket isn't in yet and silently lost. Anything published
    # while we're still inside accept() just queues on the bounded connection
    # queue and is delivered once the pump starts.
    pump_task: asyncio.Future[None] | None = None
    recv_task: asyncio.Future[bool] | None = None
    try:
        await websocket.accept()
        pump_task = asyncio.ensure_future(pump(conn, websocket.send_text))
        recv_task = asyncio.ensure_future(
            _drain_incoming(
                websocket,
                max_bytes=settings.ws_max_inbound_bytes,
                max_messages_per_second=settings.ws_max_inbound_messages_per_second,
            )
        )
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
