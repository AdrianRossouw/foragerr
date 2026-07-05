"""In-process event bus: typed delivery, isolation, post-commit publication
(FRG-SCHED-009)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pytest

from foragerr.db import CommandRow, queue_event, utcnow
from foragerr.events import EventBus


@dataclass
class SeriesAdded:
    series_id: int


@dataclass
class IssueGrabbed:
    issue_id: int


@pytest.mark.req("FRG-SCHED-009")
async def test_subscribers_receive_published_events_by_type():
    bus = EventBus()
    sync_seen: list[SeriesAdded] = []
    async_seen: list[SeriesAdded] = []
    other_seen: list[IssueGrabbed] = []

    bus.subscribe(SeriesAdded, sync_seen.append)

    async def async_handler(event: SeriesAdded) -> None:
        async_seen.append(event)

    bus.subscribe(SeriesAdded, async_handler)
    bus.subscribe(IssueGrabbed, other_seen.append)

    event = SeriesAdded(series_id=42)
    bus.publish(event)
    await bus.drain()

    assert sync_seen == [event]  # both same-type handlers invoked
    assert async_seen == [event]
    assert other_seen == []  # different event type: not invoked


@pytest.mark.req("FRG-SCHED-009")
async def test_throwing_handler_does_not_affect_others_or_publisher(caplog):
    bus = EventBus()
    recorded: list[SeriesAdded] = []

    def throwing(event: SeriesAdded) -> None:
        raise RuntimeError("subscriber exploded")

    async def async_throwing(event: SeriesAdded) -> None:
        raise RuntimeError("async subscriber exploded")

    bus.subscribe(SeriesAdded, throwing)
    bus.subscribe(SeriesAdded, async_throwing)
    bus.subscribe(SeriesAdded, recorded.append)

    with caplog.at_level(logging.ERROR, logger="foragerr.events"):
        bus.publish(SeriesAdded(series_id=1))  # publish completes normally
        await bus.drain()

    assert recorded == [SeriesAdded(series_id=1)]  # recorder ran to completion
    logged = " ".join(record.getMessage() for record in caplog.records)
    assert "handler" in logged and "failed" in logged  # exceptions were logged
    assert len([r for r in caplog.records if r.exc_info]) == 2


@pytest.mark.req("FRG-SCHED-009")
@pytest.mark.req("FRG-DB-007")
async def test_db_events_publish_only_after_commit_via_bus(db):
    bus = EventBus()
    db.event_publisher = bus.publish  # the production wiring
    seen: list[SeriesAdded] = []
    bus.subscribe(SeriesAdded, seen.append)

    # Rolled-back transaction: no subscriber ever observes the event.
    with pytest.raises(RuntimeError):
        async with db.write_session() as session:
            session.add(
                CommandRow(
                    name="noop",
                    status="queued",
                    payload="{}",
                    payload_hash="a",
                    queued_at=utcnow(),
                )
            )
            queue_event(session, SeriesAdded(series_id=7))
            raise RuntimeError("abort before commit")
    await bus.drain()
    assert seen == []

    # Committed transaction: the event arrives, strictly after commit.
    async with db.write_session() as session:
        session.add(
            CommandRow(
                name="noop",
                status="queued",
                payload="{}",
                payload_hash="b",
                queued_at=utcnow(),
            )
        )
        queue_event(session, SeriesAdded(series_id=8))
        assert seen == []  # not visible inside the transaction
    await bus.drain()
    assert seen == [SeriesAdded(series_id=8)]
