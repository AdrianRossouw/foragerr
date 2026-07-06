"""WebSocket resource-change push (FRG-API-010).

Drives the real broadcaster, event→message mapping, per-socket queues, and the
``/api/v1/ws`` endpoint coroutine against an injected fake socket + a real
:class:`EventBus`, plus a create_app wiring check. No HTTP polling anywhere —
messages arrive purely from event publication, which is the load-bearing claim.
"""

from __future__ import annotations

import asyncio
import json
import types

import pytest
from fastapi import WebSocketDisconnect

from foragerr.commands.service import CommandStatusChanged
from foragerr.downloads.tracking import DownloadFailedEvent, TrackedStateChanged
from foragerr.events import EventBus
from foragerr.library.flows import SeriesRefreshed
from foragerr.ws import WsBroadcaster
from foragerr.ws.broadcast import Connection, pump
from foragerr.ws.messages import map_event
from foragerr.ws.router import ws_endpoint


def _drain(conn: Connection) -> list[dict]:
    """Pull and JSON-decode everything currently queued for one connection."""
    out: list[dict] = []
    while not conn.queue.empty():
        out.append(json.loads(conn.queue.get_nowait()))
    return out


def _tracked(download_id: str, issue_id: int) -> TrackedStateChanged:
    return TrackedStateChanged(
        download_id=download_id,
        state="downloading",
        status="ok",
        series_id=1,
        issue_id=issue_id,
    )


# -- event → message mapping --------------------------------------------------


@pytest.mark.req("FRG-API-010")
def test_map_event_covers_queue_series_command_and_ignores_the_rest():
    q = map_event(_tracked("d1", 2))
    assert q == (
        "queue",
        "updated",
        {
            "downloadId": "d1",
            "status": "downloading",  # lifecycle state string the UI calls status
            "health": "ok",
            "seriesId": 1,
            "issueId": 2,
        },
    )
    assert map_event(SeriesRefreshed(series_id=5, partial=True)) == (
        "series",
        "updated",
        {"id": 5, "partial": True},
    )
    assert map_event(CommandStatusChanged(id=3, name="grab", status="completed")) == (
        "command",
        "updated",
        {"id": 3, "name": "grab", "status": "completed"},
    )
    failed = DownloadFailedEvent(
        download_id="fx",
        source_title=None,
        guid=None,
        indexer_id=None,
        indexer_name=None,
        size_bytes=None,
        publish_date=None,
        protocol=None,
        source=None,
        issues=((1, 2), (1, 3)),
    )
    assert map_event(failed) == (
        "queue",
        "updated",
        {"downloadId": "fx", "status": "failed", "issues": [[1, 2], [1, 3]]},
    )
    assert map_event(object()) is None  # unmapped -> dropped


@pytest.mark.req("FRG-API-010")
def test_map_event_covers_the_daily_surface_families():
    """The daily-surfaces emitters (gate fix): history/wanted/blocklist writes
    now announce themselves so those screens invalidate without a queue push."""
    from foragerr.downloads.tracking import BlocklistChanged
    from foragerr.importer.history import HistoryEventRecorded, WantedInvalidated

    assert map_event(HistoryEventRecorded(event_type="imported", series_id=4)) == (
        "history",
        "updated",
        {"eventType": "imported", "seriesId": 4},
    )
    assert map_event(WantedInvalidated(series_id=4)) == (
        "wanted",
        "updated",
        {"seriesId": 4},
    )
    assert map_event(BlocklistChanged()) == ("blocklist", "updated", {})


@pytest.mark.req("FRG-API-010")
async def test_import_history_write_pushes_history_and_wanted_frames(db):
    """End-to-end: a file-presence history write (an import) queued inside a
    write_session reaches a WS client as BOTH a `history` and a `wanted`
    invalidation frame — the two screens the frontend infers from these."""
    from foragerr.importer import history

    bus = EventBus()
    broadcaster = WsBroadcaster(debounce_seconds=0.02)
    broadcaster.subscribe(bus)
    conn = broadcaster.connect()
    db.event_publisher = bus.publish  # wire post-commit delivery to the bus

    async with db.write_session() as session:
        history.record_event(
            session,
            event_type=history.EVENT_IMPORTED,
            series_id=1,
            issue_id=2,
            source=history.SOURCE_MANUAL,
            data={"imported_path": "/lib/x.cbz"},
        )
    await asyncio.sleep(0.06)

    by = {(m["name"], m["action"]) for m in _drain(conn)}
    assert ("history", "updated") in by
    assert ("wanted", "updated") in by


@pytest.mark.req("FRG-API-010")
async def test_grabbed_history_write_pushes_history_only_not_wanted(db):
    """A `grabbed` event changes no file presence, so it invalidates history
    but NOT wanted (only import/upgrade/delete move the missing list)."""
    from foragerr.importer import history

    bus = EventBus()
    broadcaster = WsBroadcaster(debounce_seconds=0.02)
    broadcaster.subscribe(bus)
    conn = broadcaster.connect()
    db.event_publisher = bus.publish

    async with db.write_session() as session:
        history.record_event(
            session,
            event_type=history.EVENT_GRABBED,
            series_id=1,
            issue_id=2,
            download_id="nzo-1",
            source=history.SOURCE_DOWNLOAD,
            data={"indexer": "DogNZB"},
        )
    await asyncio.sleep(0.06)

    by = {(m["name"], m["action"]) for m in _drain(conn)}
    assert ("history", "updated") in by
    assert ("wanted", "updated") not in by


# -- push without polling -----------------------------------------------------


@pytest.mark.req("FRG-API-010")
async def test_resource_change_is_pushed_without_polling():
    bus = EventBus()
    broadcaster = WsBroadcaster(debounce_seconds=0.02)
    broadcaster.subscribe(bus)
    conn = broadcaster.connect()

    # A grab: the queue changes AND the driving command reaches a terminal state.
    bus.publish(_tracked("d1", 2))
    bus.publish(CommandStatusChanged(id=7, name="grab", status="completed"))
    await asyncio.sleep(0.06)

    by = {(m["name"], m["action"]): m["resource"] for m in _drain(conn)}
    assert by[("queue", "updated")]["downloadId"] == "d1"
    assert by[("queue", "updated")]["status"] == "downloading"
    assert by[("command", "updated")] == {
        "id": 7,
        "name": "grab",
        "status": "completed",
    }


# -- debounce / coalescing ----------------------------------------------------


@pytest.mark.req("FRG-API-010")
async def test_burst_of_updates_to_one_resource_coalesces_to_one_message():
    bus = EventBus()
    broadcaster = WsBroadcaster(debounce_seconds=0.05)
    broadcaster.subscribe(bus)
    conn = broadcaster.connect()

    # 25 progress ticks for the SAME download collapse to one last-wins message.
    for i in range(25):
        bus.publish(_tracked("d1", i))
    await asyncio.sleep(0.12)

    msgs = _drain(conn)
    assert len(msgs) == 1  # one resource, one broadcast
    assert msgs[0]["resource"]["downloadId"] == "d1"
    assert msgs[0]["resource"]["issueId"] == 24  # last-wins coalesce


@pytest.mark.req("FRG-API-010")
async def test_distinct_resources_in_one_window_each_get_a_message():
    """Two DIFFERENT downloads progressing inside one debounce window must both
    be delivered — coalescing on (name, action) alone silently drops one row's
    update, which the frontend patches by id."""
    bus = EventBus()
    broadcaster = WsBroadcaster(debounce_seconds=0.05)
    broadcaster.subscribe(bus)
    conn = broadcaster.connect()

    bus.publish(_tracked("d1", 1))
    bus.publish(_tracked("d2", 2))
    await asyncio.sleep(0.12)

    ids = sorted(m["resource"]["downloadId"] for m in _drain(conn))
    assert ids == ["d1", "d2"]  # BOTH broadcast; neither clobbers the other


@pytest.mark.req("FRG-API-010")
async def test_distinct_families_each_get_one_message_per_window():
    bus = EventBus()
    broadcaster = WsBroadcaster(debounce_seconds=0.05)
    broadcaster.subscribe(bus)
    conn = broadcaster.connect()

    for i in range(5):
        bus.publish(_tracked(f"d{i}", i))
    bus.publish(SeriesRefreshed(series_id=1, partial=False))
    bus.publish(SeriesRefreshed(series_id=2, partial=False))
    await asyncio.sleep(0.12)

    by = {(m["name"], m["action"]) for m in _drain(conn)}
    assert by == {("queue", "updated"), ("series", "updated")}


# -- slow-client isolation ----------------------------------------------------


@pytest.mark.req("FRG-API-010")
async def test_slow_client_is_dropped_and_never_blocks_the_others():
    broadcaster = WsBroadcaster(queue_maxsize=2)
    slow = broadcaster.connect()
    fast = broadcaster.connect()

    broadcaster._broadcast('{"n":1}')
    broadcaster._broadcast('{"n":2}')  # both queues now full (2/2)
    fast.queue.get_nowait()  # fast drains; slow does not
    fast.queue.get_nowait()

    broadcaster._broadcast('{"n":3}')  # slow overflows -> dropped; fast receives
    assert slow.dropped.is_set()
    assert slow not in broadcaster._connections
    assert fast in broadcaster._connections
    assert fast.queue.get_nowait() == '{"n":3}'

    broadcaster._broadcast('{"n":4}')  # the bus keeps flowing to the survivor
    assert fast.queue.get_nowait() == '{"n":4}'
    assert broadcaster.connection_count == 1


@pytest.mark.req("FRG-API-010")
async def test_pump_forwards_messages_then_returns_on_drop():
    conn = Connection(4)
    sent: list[str] = []

    async def send(text: str) -> None:
        sent.append(text)

    task = asyncio.ensure_future(pump(conn, send))
    conn.queue.put_nowait("a")
    await asyncio.sleep(0.02)
    assert sent == ["a"]

    conn.dropped.set()
    await asyncio.wait_for(task, 1.0)  # returns promptly once dropped


# -- reconnect resumption -----------------------------------------------------


@pytest.mark.req("FRG-API-010")
async def test_reconnecting_client_resumes_receiving():
    bus = EventBus()
    broadcaster = WsBroadcaster(debounce_seconds=0.02)
    broadcaster.subscribe(bus)

    first = broadcaster.connect()
    bus.publish(SeriesRefreshed(series_id=1, partial=False))
    await asyncio.sleep(0.06)
    assert len(_drain(first)) == 1

    broadcaster.disconnect(first)  # client goes away...
    second = broadcaster.connect()  # ...and later reconnects
    bus.publish(SeriesRefreshed(series_id=2, partial=False))
    await asyncio.sleep(0.06)

    got = _drain(second)
    assert len(got) == 1 and got[0]["resource"]["id"] == 2
    assert first.queue.empty()  # the gone socket receives nothing more


# -- endpoint end-to-end (real router + pump + bus) ---------------------------


class _FakeWebSocket:
    """Minimal WebSocket stand-in that drives the endpoint on one loop."""

    def __init__(self, app: object) -> None:
        self.app = app
        self.sent: list[str] = []
        self.accepted = False
        self.closed = False
        self._incoming: asyncio.Queue[object] = asyncio.Queue()

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, text: str) -> None:
        self.sent.append(text)

    async def receive_text(self) -> str:
        item = await self._incoming.get()
        if isinstance(item, WebSocketDisconnect):
            raise item
        return str(item)

    async def close(self, code: int = 1000) -> None:
        self.closed = True


def _fake_app(broadcaster: WsBroadcaster) -> object:
    return types.SimpleNamespace(
        state=types.SimpleNamespace(ws_broadcaster=broadcaster)
    )


@pytest.mark.req("FRG-API-010")
async def test_endpoint_pushes_then_cleans_up_on_client_disconnect():
    bus = EventBus()
    broadcaster = WsBroadcaster(debounce_seconds=0.02)
    broadcaster.subscribe(bus)
    ws = _FakeWebSocket(_fake_app(broadcaster))

    endpoint = asyncio.ensure_future(ws_endpoint(ws))
    await asyncio.sleep(0.02)
    assert ws.accepted and broadcaster.connection_count == 1

    bus.publish(SeriesRefreshed(series_id=9, partial=False))
    await asyncio.sleep(0.06)
    assert any(json.loads(t)["resource"]["id"] == 9 for t in ws.sent)

    ws._incoming.put_nowait(WebSocketDisconnect(1000))  # client disconnects
    await asyncio.wait_for(endpoint, 1.0)
    # The endpoint deregisters, but does NOT re-close a socket the CLIENT
    # already closed — closing a gone socket races the ASGI teardown (that
    # race surfaced as a CancelledError escaping the real-ASGI test). The
    # cleanup guarantee is deregistration, not a server-side close here.
    assert not ws.closed
    assert broadcaster.connection_count == 0


@pytest.mark.req("FRG-API-010")
async def test_endpoint_closes_a_dropped_slow_client():
    broadcaster = WsBroadcaster(queue_maxsize=2)
    ws = _FakeWebSocket(_fake_app(broadcaster))

    endpoint = asyncio.ensure_future(ws_endpoint(ws))
    await asyncio.sleep(0.02)
    conn = next(iter(broadcaster._connections))

    conn.dropped.set()  # broadcaster judged this client too slow
    await asyncio.wait_for(endpoint, 1.0)
    assert ws.closed
    assert broadcaster.connection_count == 0


class _PublishDuringAcceptWebSocket(_FakeWebSocket):
    """Publishes a domain event while the endpoint is still inside accept().

    Reproduces (deterministically) the race the full suite exposed under load:
    a client whose handshake has completed publishes/observes an event before
    the endpoint coroutine resumes. Registration must precede accept or the
    broadcast fans out to a registry this socket is not in yet and the message
    is silently lost.
    """

    def __init__(self, app: object, bus: EventBus) -> None:
        super().__init__(app)
        self._bus = bus

    async def accept(self) -> None:
        self._bus.publish(SeriesRefreshed(series_id=77, partial=False))
        # A real sleep so the (zero-second) debounce timer fires — i.e. the
        # broadcast fan-out happens — while we are still inside accept().
        await asyncio.sleep(0.01)
        await super().accept()


@pytest.mark.req("FRG-API-010")
async def test_event_published_during_accept_is_not_lost():
    bus = EventBus()
    broadcaster = WsBroadcaster(debounce_seconds=0.0)
    broadcaster.subscribe(bus)
    ws = _PublishDuringAcceptWebSocket(_fake_app(broadcaster), bus)

    endpoint = asyncio.ensure_future(ws_endpoint(ws))
    await asyncio.sleep(0.05)
    assert any(json.loads(t)["resource"]["id"] == 77 for t in ws.sent), (
        "an event published while the endpoint was inside accept() was lost — "
        "the connection must be registered with the broadcaster BEFORE accept"
    )

    ws._incoming.put_nowait(WebSocketDisconnect(1000))
    await asyncio.wait_for(endpoint, 1.0)
    assert broadcaster.connection_count == 0


# -- app wiring ---------------------------------------------------------------


@pytest.mark.req("FRG-API-010")
def test_ws_endpoint_delivers_a_push_over_the_real_asgi_stack(tmp_path):
    """End-to-end through create_app + a real WebSocket: publishing a domain
    event on ``app.state.events`` reaches a connected ``/api/v1/ws`` client as
    the wire envelope — no HTTP poll involved."""
    from fastapi.testclient import TestClient

    from foragerr.app import create_app
    from foragerr.config import Settings

    cfg = tmp_path / "cfg"
    cfg.mkdir()
    app = create_app(Settings(config_dir=cfg))

    with TestClient(app) as client:
        broadcaster = client.app.state.ws_broadcaster
        assert isinstance(broadcaster, WsBroadcaster)
        # Subscribed to the same bus the scheduler area created.
        assert broadcaster._bus is client.app.state.events

        with client.websocket_connect("/api/v1/ws") as ws:
            # Publish on the app's event loop via the test session's portal.
            ws.portal.call(
                client.app.state.events.publish,
                SeriesRefreshed(series_id=42, partial=False),
            )
            # The app's own startup activity (scheduler/command events) may
            # legitimately broadcast in the same window under load — the
            # claim under test is that OUR envelope arrives, not that it
            # arrives first. Read a bounded handful of messages.
            expected = {
                "name": "series",
                "action": "updated",
                "resource": {"id": 42, "partial": False},
            }
            received = []
            for _ in range(20):
                msg = json.loads(ws.receive_text())
                received.append(msg)
                if msg == expected:
                    break
            assert expected in received, f"push never arrived; saw {received!r}"
            # Close explicitly from the client side so the endpoint observes the
            # disconnect and skips its own close() — keeping the portal teardown
            # (this `with` block's __exit__) from racing a double close.
            ws.close()
