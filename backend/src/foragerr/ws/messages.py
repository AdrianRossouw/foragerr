"""Domain-event → WebSocket push-message mapping (FRG-API-010).

Every message the endpoint broadcasts is the SignalR-shaped envelope the
frontend bridge consumes (``frontend/src/ws/messages.ts``)::

    {"name": <resource family>, "action": <verb>, "resource": <payload>}

The bus publishes concrete domain events; :func:`map_event` is the single
place they become that wire envelope. Events with no mapping return ``None``
and are dropped, so subscribing to the base ``object`` type on the bus (to
catch every family without enumerating them at subscribe time) stays safe.

Divergence from the scaffold's queue-progress contract (reported, not hidden)
-----------------------------------------------------------------------------
``frontend/src/ws/messages.ts`` models a ``{name:'queue', action:'progress'}``
message carrying ``{id, page, progress, sizeLeft, status}`` and PATCHES the
cached page in place. The backend cannot produce that message from the events
it actually emits:

* :class:`TrackedStateChanged` fires only on a state TRANSITION, not on every
  byte-count tick, and carries the string ``download_id`` — not the numeric
  ``tracked_downloads.id`` the queue rows are keyed by, and no ``size``/
  ``sizeleft``/``progress`` fields.
* ``page`` is a React-Query pagination concept the backend has no knowledge of.

So queue changes are emitted as ``{name:'queue', action:'updated'}`` — an
INVALIDATION signal — and the frontend must refetch the queue query on it
rather than patch. The scaffold bridge only patches (action ``progress``) or
invalidates ``series``; it needs a queue-invalidation branch to consume these.
Live byte-level progress patching is deferred (needs a per-tick event carrying
the numeric id + sizes; M2).
"""

from __future__ import annotations

from typing import Any

from foragerr.commands.service import CommandStatusChanged
from foragerr.downloads.tracking import DownloadFailedEvent, TrackedStateChanged
from foragerr.library.flows import SeriesRefreshed

#: (name, action, resource) — the three fields of the wire envelope.
ResourceMessage = tuple[str, str, dict[str, Any]]


def map_event(event: Any) -> ResourceMessage | None:
    """Translate a published domain event into a push envelope, or ``None``.

    Coverage (FRG-API-010): queue (tracked-download state + failures), series
    (metadata refresh), command (status change). Issue-file changes have no
    backend emitter in M1 (design note: M1 scopes broadcast to queue+command);
    the mapping is trivially extensible when such an event lands.
    """
    if isinstance(event, TrackedStateChanged):
        # `status` here is the lifecycle state string the frontend calls
        # `status`; `health` is the ok/warning/error rollup (backend `status`).
        return (
            "queue",
            "updated",
            {
                "downloadId": event.download_id,
                "status": event.state,
                "health": event.status,
                "seriesId": event.series_id,
                "issueId": event.issue_id,
            },
        )
    if isinstance(event, DownloadFailedEvent):
        return (
            "queue",
            "updated",
            {
                "downloadId": event.download_id,
                "status": "failed",
                "issues": [list(pair) for pair in event.issues],
            },
        )
    if isinstance(event, SeriesRefreshed):
        return ("series", "updated", {"id": event.series_id, "partial": event.partial})
    if isinstance(event, CommandStatusChanged):
        return (
            "command",
            "updated",
            {"id": event.id, "name": event.name, "status": event.status},
        )
    return None


__all__ = ["ResourceMessage", "map_event"]
