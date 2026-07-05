"""In-process typed event bus (FRG-SCHED-009).

Handlers subscribe by event type (isinstance matching, so subscribing to a
base class receives subclasses). Synchronous handlers run inline inside a
try/except; async handlers run fire-and-forget in their own task. Either way
a handler's exception is logged and never affects other handlers or the
publisher.

Post-commit publication (FRG-DB-007): the sched area wires
``Database.event_publisher = bus.publish`` so events queued with
``foragerr.db.queue_event()`` inside a ``write_session()`` are delivered only
after the transaction commits.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Callable

logger = logging.getLogger("foragerr.events")

__all__ = ["Event", "EventBus"]


class Event:
    """Optional base class for domain events (any type may be published)."""


class EventBus:
    """Typed publish/subscribe with per-handler isolation."""

    def __init__(self) -> None:
        self._subscribers: list[tuple[type, Callable[[Any], Any]]] = []
        self._pending: set[asyncio.Task[None]] = set()

    def subscribe(self, event_type: type, handler: Callable[[Any], Any]) -> None:
        """Invoke ``handler`` for every published event of ``event_type``."""
        self._subscribers.append((event_type, handler))

    def unsubscribe(self, event_type: type, handler: Callable[[Any], Any]) -> None:
        self._subscribers.remove((event_type, handler))

    def publish(self, event: Any) -> None:
        """Deliver ``event`` to every matching handler, each isolated."""
        for event_type, handler in list(self._subscribers):
            if not isinstance(event, event_type):
                continue
            if inspect.iscoroutinefunction(handler):
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    logger.error(
                        "events: no running loop to deliver %s to async handler %r",
                        type(event).__name__,
                        handler,
                    )
                    continue
                task = loop.create_task(self._run_async(handler, event))
                self._pending.add(task)
                task.add_done_callback(self._pending.discard)
            else:
                try:
                    handler(event)
                except Exception:
                    logger.exception(
                        "events: handler %r failed for %s (isolated)",
                        handler,
                        type(event).__name__,
                    )

    async def _run_async(self, handler: Callable[[Any], Any], event: Any) -> None:
        try:
            await handler(event)
        except Exception:
            logger.exception(
                "events: async handler %r failed for %s (isolated)",
                handler,
                type(event).__name__,
            )

    async def drain(self) -> None:
        """Wait for fire-and-forget handler tasks to finish (shutdown/tests)."""
        while self._pending:
            await asyncio.gather(*list(self._pending), return_exceptions=True)
