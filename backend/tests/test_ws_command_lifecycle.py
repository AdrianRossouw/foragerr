"""FRG-SCHED-010 — every command lifecycle transition reaches a WS client:
queued, the started claim (the gap this change closes), and the terminal
outcome, through the REAL bridge (write_session post-commit publication →
EventBus → WsBroadcaster) with the debounce/coalescing window respected."""

from __future__ import annotations

import asyncio
import json

import pytest

from foragerr.commands import CommandService
from foragerr.commands.registry import register_handler
from foragerr.events import EventBus
from foragerr.ws import WsBroadcaster
from foragerr.ws.broadcast import Connection

from conftest import define_command, eventually


def _drain(conn: Connection) -> list[dict]:
    out: list[dict] = []
    while not conn.queue.empty():
        out.append(json.loads(conn.queue.get_nowait()))
    return out


@pytest.mark.req("FRG-SCHED-010")
async def test_ws_client_observes_queued_started_and_terminal(
    db, command_registry
):
    """Drive one command through the real service + bus + broadcaster and
    assert a connected client observes all three lifecycle statuses.

    Coalescing (100 ms window, last-wins per resource id) may legally merge
    transitions that land inside one window, so the test holds the handler at
    a gate: queued flushes before the workers start, started flushes while the
    handler is parked, and the terminal state flushes after the gate opens —
    each transition gets its own debounce window, exactly the shape a real
    long-running command has. Frames are POLLED from the client queue (never
    a fixed-count read) so the window timing stays respected, not raced.
    """
    bus = EventBus()
    db.event_publisher = bus.publish  # the app factory's exact wiring
    broadcaster = WsBroadcaster(debounce_seconds=0.02)
    broadcaster.subscribe(bus)
    conn = broadcaster.connect()

    define_command("t_ws_lifecycle")
    gate = asyncio.Event()

    @register_handler("t_ws_lifecycle")
    async def _gated(command, ctx):
        await gate.wait()
        return "done"

    service = CommandService(db, poll_interval=0.05)
    seen: list[dict] = []

    def _statuses(command_id: int) -> list[str]:
        seen.extend(_drain(conn))
        return [
            m["resource"]["status"]
            for m in seen
            if m["name"] == "command"
            and m["action"] == "updated"
            and m["resource"]["id"] == command_id
            and m["resource"]["name"] == "t_ws_lifecycle"
        ]

    try:
        # Enqueue BEFORE the workers run: the queued push flushes in its own
        # debounce window, uncontested by the claim.
        record = await service.enqueue("t_ws_lifecycle", {"token": "x"})
        await eventually(lambda: "queued" in _statuses(record.id))

        # Workers start; the claim commits `started` while the handler is
        # parked at the gate — the transition the M1 bridge never emitted.
        await service.start()
        await eventually(lambda: "started" in _statuses(record.id))

        # Open the gate; the terminal outcome always lands (never skipped).
        gate.set()
        await eventually(lambda: "completed" in _statuses(record.id))

        assert _statuses(record.id) == ["queued", "started", "completed"]
    finally:
        await service.drain(1.0)
        broadcaster.unsubscribe()
