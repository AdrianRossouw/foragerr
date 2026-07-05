"""Scheduled backlog search with politeness (FRG-SRCH-009)."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from foragerr.commands.registry import get_handler
from foragerr.providers.backoff import PROVIDER_INDEXER, ProviderBackoff
from foragerr.search_ops.commands import (
    BACKLOG_MIN_DELAY_SECONDS,
    BacklogSearchCommand,
    effective_backlog_delay,
)
from http_support import make_settings
from indexers_support import make_factory  # noqa: F401
from .support import (
    feed_handler,
    grab_rows,
    make_ctx,
    make_indexer,
    make_issue,
    make_series,
    patch_pipeline_factory,
)


@pytest.fixture(autouse=True)
def _fast_interval(monkeypatch):
    import foragerr.search_ops.commands as commands

    monkeypatch.setattr(commands, "MIN_INTERVAL", 0.0)


def _capture_sleeps(monkeypatch) -> list[float]:
    """Record politeness delays instead of actually sleeping."""
    import foragerr.search_ops.commands as commands

    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(commands, "_politeness_sleep", fake_sleep)
    return sleeps


@pytest.mark.req("FRG-SRCH-009")
def test_delay_defaults_to_the_floor_without_settings():
    assert effective_backlog_delay(None) == BACKLOG_MIN_DELAY_SECONDS


@pytest.mark.req("FRG-SRCH-009")
def test_delay_clamp_respects_a_larger_configured_value(tmp_path):
    settings = make_settings(tmp_path, backlog_search_delay_seconds=5)
    assert effective_backlog_delay(settings) == BACKLOG_MIN_DELAY_SECONDS
    settings = make_settings(tmp_path, backlog_search_delay_seconds=120)
    assert effective_backlog_delay(settings) == 120


@pytest.mark.req("FRG-SRCH-009")
async def test_backlog_walks_wanted_issues_oldest_first_with_spacing(
    db, format_profile_id, root_folder_id, monkeypatch, tmp_path
):
    series_id = await make_series(
        db, format_profile_id=format_profile_id, root_folder_id=root_folder_id
    )
    # Three wanted issues with distinct release dates (newest inserted first).
    newest = await make_issue(
        db, series_id=series_id, issue_number="9", cover_date=dt.date(2022, 3, 1)
    )
    oldest = await make_issue(
        db, series_id=series_id, issue_number="7", cover_date=dt.date(2020, 1, 1)
    )
    middle = await make_issue(
        db, series_id=series_id, issue_number="8", cover_date=dt.date(2021, 2, 1)
    )
    await make_indexer(db)

    order: list[str] = []

    def recording_handler():
        base = feed_handler("Saga 007 (2012)", "Saga 008 (2012)", "Saga 009 (2012)")

        def handler(request):
            if request.url.params.get("t") == "search":
                order.append(request.url.params.get("q"))
            return base(request)

        return handler

    patch_pipeline_factory(monkeypatch, tmp_path, recording_handler())
    sleeps = _capture_sleeps(monkeypatch)

    ctx = make_ctx(db, make_settings(tmp_path))
    await get_handler("backlog-search")(BacklogSearchCommand(), ctx)

    # Oldest-first: the tier-0 (most specific) query for issue 7 precedes 8, 8 precedes 9.
    def first_index(issue_q: str) -> int:
        return next(i for i, q in enumerate(order) if issue_q in q)

    assert first_index("7") < first_index("8") < first_index("9")
    # Politeness spacing applied between the three issues (n-1 gaps), clamped.
    assert sleeps == [BACKLOG_MIN_DELAY_SECONDS, BACKLOG_MIN_DELAY_SECONDS]
    # A grab hand-off recorded for each wanted issue.
    grabbed = {r.payload for r in await grab_rows(db)}
    assert len(grabbed) == 3
    assert {oldest, middle, newest}  # referenced


@pytest.mark.req("FRG-SRCH-009")
async def test_backing_off_indexer_is_skipped(
    db, format_profile_id, root_folder_id, monkeypatch, tmp_path
):
    series_id = await make_series(
        db, format_profile_id=format_profile_id, root_folder_id=root_folder_id
    )
    issue_id = await make_issue(db, series_id=series_id, issue_number="7")
    indexer_id = await make_indexer(db)

    # Put the only indexer deep into its back-off window.
    backoff = ProviderBackoff(db)
    await backoff.record_failure(
        PROVIDER_INDEXER, indexer_id, reason="forced", fast_forward=True
    )
    assert await backoff.is_backing_off(PROVIDER_INDEXER, indexer_id)

    transport = patch_pipeline_factory(
        monkeypatch, tmp_path, feed_handler("Saga 007 (2012)")
    )
    _capture_sleeps(monkeypatch)
    ctx = make_ctx(db, make_settings(tmp_path))
    await get_handler("backlog-search")(BacklogSearchCommand(), ctx)

    # No request was issued to the backing-off indexer, and nothing was grabbed.
    assert transport.requests == []
    assert await grab_rows(db) == []


@pytest.mark.req("FRG-SRCH-009")
async def test_backlog_is_restart_safe_via_orphan_recovery(
    db, format_profile_id, root_folder_id
):
    """A backlog command left ``started`` by a dead process is re-queued by the
    persisted command queue's orphan recovery, not lost (restart-safe)."""
    from foragerr.commands.service import CommandService
    from foragerr.db import CommandRow, utcnow

    # Simulate a mid-run crash: a started backlog-search row on the queue.
    async with db.write_session() as session:
        session.add(
            CommandRow(
                name="backlog-search",
                status="started",
                priority=0,
                workload_class="search",
                exclusivity_group="backlog-search",
                payload="{}",
                payload_hash="deadbeef",
                triggered_by="scheduled",
                queued_at=utcnow(),
                started_at=utcnow(),
            )
        )

    service = CommandService(db, make_settings(db.db_path.parent))
    recovered = await service.recover_orphans()
    assert recovered == 1

    async with db.read_session() as session:
        row = (
            await session.execute(
                select(CommandRow).where(CommandRow.name == "backlog-search")
            )
        ).scalar_one()
    assert row.status == "queued"  # re-queued to resume, not abandoned
