"""WebSocket broadcast fan-out: bus subscriber + per-socket send queues.

The :class:`WsBroadcaster` is the asyncio equivalent of Sonarr's SignalR
broadcaster (FRG-API-010). It subscribes to the in-process event bus, coalesces
a burst of same-``(name, action)`` changes over a ~100 ms window into a single
message, and pushes each broadcast onto a BOUNDED per-socket queue. A client
that stops draining its queue fills it, is dropped, and never stalls the bus or
the other clients — the load-bearing isolation property.

Threading model: every method here runs on the single app event loop (the bus
delivers ``_on_event`` inline during ``publish``; the debounce flush is a
``loop.call_later`` callback; the per-socket :func:`pump` is an awaiting task).
No locks are needed — there is exactly one thread of control.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable

from foragerr.events import EventBus
from foragerr.ws.messages import map_event

logger = logging.getLogger("foragerr.ws")

#: Debounce/coalesce window: a burst of same-(name, action) events inside this
#: many seconds collapses to one broadcast (spec: ~100 ms).
DEFAULT_DEBOUNCE_SECONDS = 0.1

#: Per-socket send-queue depth. A client that lets this many broadcasts back up
#: (never draining its socket) is judged too slow and dropped.
DEFAULT_QUEUE_MAXSIZE = 64


class Connection:
    """One connected client: a bounded outbound queue plus a drop signal."""

    __slots__ = ("queue", "dropped")

    def __init__(self, maxsize: int) -> None:
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=maxsize)
        #: Set by the broadcaster when this client's queue overflowed; the
        #: socket's :func:`pump` observes it and closes the connection.
        self.dropped: asyncio.Event = asyncio.Event()

    def offer(self, text: str) -> bool:
        """Enqueue without ever blocking; ``False`` means the queue was full."""
        try:
            self.queue.put_nowait(text)
            return True
        except asyncio.QueueFull:
            return False


class WsBroadcaster:
    """Event-bus subscriber that debounces and fans out to per-socket queues."""

    def __init__(
        self,
        *,
        debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS,
        queue_maxsize: int = DEFAULT_QUEUE_MAXSIZE,
    ) -> None:
        self._debounce = debounce_seconds
        self._queue_maxsize = queue_maxsize
        self._connections: set[Connection] = set()
        #: (name, action, identity) -> latest resource in the current debounce
        #: window. Keying on the resource identity (not just name+action) keeps
        #: two DISTINCT resources changing in one window from clobbering each
        #: other — the frontend patches specific rows by id from these payloads.
        self._pending: dict[tuple[str, str, Any], dict[str, Any]] = {}
        self._flush_handle: asyncio.TimerHandle | None = None
        self._bus: EventBus | None = None

    # -- bus wiring ----------------------------------------------------------

    def subscribe(self, bus: EventBus) -> None:
        """Receive EVERY published domain event (``object`` matches all).

        :func:`map_event` filters to the mapped families; subscribing broadly
        means a new resource family only needs a mapping, not a subscribe call.
        """
        bus.subscribe(object, self._on_event)
        self._bus = bus

    def unsubscribe(self) -> None:
        """Detach from the bus and cancel any pending flush (shutdown)."""
        if self._bus is not None:
            self._bus.unsubscribe(object, self._on_event)
            self._bus = None
        if self._flush_handle is not None:
            self._flush_handle.cancel()
            self._flush_handle = None

    # -- connection registry -------------------------------------------------

    def connect(self) -> Connection:
        """Register a new client socket and return its connection handle."""
        conn = Connection(self._queue_maxsize)
        self._connections.add(conn)
        return conn

    def disconnect(self, conn: Connection) -> None:
        """Remove a client socket (client disconnect or endpoint teardown)."""
        self._connections.discard(conn)

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    # -- ingest + debounce ---------------------------------------------------

    def _on_event(self, event: Any) -> None:
        """Bus handler: map the event and open/extend the debounce window."""
        mapped = map_event(event)
        if mapped is None:
            return
        name, action, resource = mapped
        # Last-wins coalesce PER RESOURCE: a burst of updates for the SAME
        # resource yields one message, but two different resources each keep
        # their own — otherwise one row's update is silently lost. Identity is
        # the resource's id field ("id", else "downloadId"); an id-less payload
        # coalesces on (name, action) as before.
        identity = resource.get("id", resource.get("downloadId"))
        self._pending[(name, action, identity)] = resource
        self._schedule_flush()

    def _schedule_flush(self) -> None:
        if self._flush_handle is not None:
            return  # a flush is already armed for this window
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop (e.g. a synchronous harness): flush inline so the
            # message is not silently lost.
            self._flush()
            return
        self._flush_handle = loop.call_later(self._debounce, self._flush)

    def _flush(self) -> None:
        self._flush_handle = None
        if not self._pending:
            return
        batch, self._pending = self._pending, {}
        for (name, action, _identity), resource in batch.items():
            text = json.dumps(
                {"name": name, "action": action, "resource": resource},
                separators=(",", ":"),
            )
            self._broadcast(text)

    def _broadcast(self, text: str) -> None:
        """Push ``text`` onto every socket's queue; drop those that overflow."""
        overflowed = [conn for conn in self._connections if not conn.offer(text)]
        for conn in overflowed:
            logger.warning("ws: dropping slow client (send queue full)")
            self._connections.discard(conn)
            conn.dropped.set()  # tell its pump to close the socket


async def pump(conn: Connection, send: Callable[[str], Awaitable[None]]) -> None:
    """Drain ``conn``'s queue to ``send`` until dropped or the socket errors.

    Kept independent of the concrete WebSocket so the router can pass
    ``websocket.send_text`` and tests can pass a recorder. Returns (rather than
    raising) on a slow-client drop or a send failure; the endpoint's ``finally``
    owns deregistration and socket close.
    """
    while True:
        get_task = asyncio.ensure_future(conn.queue.get())
        drop_task = asyncio.ensure_future(conn.dropped.wait())
        try:
            await asyncio.wait(
                {get_task, drop_task}, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            for task in (get_task, drop_task):
                if not task.done():
                    task.cancel()
        if get_task.done() and not get_task.cancelled():
            try:
                await send(get_task.result())
            except Exception:  # noqa: BLE001 — client gone; endpoint cleans up
                return
        if drop_task.done() and not drop_task.cancelled():
            return  # slow-client drop: stop pumping, let the endpoint close


__all__ = [
    "DEFAULT_DEBOUNCE_SECONDS",
    "DEFAULT_QUEUE_MAXSIZE",
    "Connection",
    "WsBroadcaster",
    "pump",
]
