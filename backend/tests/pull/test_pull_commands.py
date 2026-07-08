"""The ``pull-refresh`` command, schedule, and refresh trigger (FRG-PULL-005/006).

Exercises area D end-to-end over the frozen contracts of the landed halves:

- **FRG-PULL-005** (refresh trigger): a full fetch → store → match → trigger
  pipeline where a matched-but-missing issue enqueues exactly one deduplicated
  ``refresh-series`` per series and writes no issue status; an already-present
  matched issue triggers none.
- **FRG-PULL-006** (scheduled + manual refresh): the enabled-gate no-op, the
  degraded-outcome note that leaves stored data intact, the config keys +
  documented rendering + interval clamp, task registration, and the
  scheduler-level throttle (a scheduled tick within the interval window is
  suppressed) vs. force-run (bypasses it).

The fetch itself (area B, FRG-PULL-002) is exhaustively covered in
``test_pull_source.py``; here the client is a stub returning a prepared outcome
so the tests focus on D's orchestration.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from conftest import seed_series_issue

from foragerr.commands.service import CommandService, HandlerContext
from foragerr.commands.scheduler import IntervalScheduler
from foragerr.config import Settings, render_documented_config
from foragerr.db import CommandRow
from foragerr.pull import commands as pull_commands
from foragerr.pull import repo
from foragerr.pull.commands import (
    PULL_REFRESH_MIN_INTERVAL_SECONDS,
    PULL_REFRESH_TASK,
    PullRefreshCommand,
    _fetch_weeks,
    _handle_pull_refresh,
    pull_refresh_task_registration,
    register_pull_refresh_task,
)
from foragerr.pull.models import ParsedPullEntry
from foragerr.pull.source import PullFetchOutcome, PullWeekResult

# 2026-07-08 (the ship date the fixtures use) is ISO week 2026-W28, so the stored
# week must be W28 — the name-match week guard (FRG-PULL-004) requires the entry's
# release date to fall within the week it is stored under.
WEEK, YEAR = 28, 2026
WEEK_KEY = f"{YEAR}-W{WEEK:02d}"


def _entry(series: str, issue: str, *, day: dt.date, cv_issue_id: int | None = None):
    return ParsedPullEntry(
        series_name=series,
        issue_number=issue,
        release_date=day,
        publisher="Image Comics",
        cv_series_id=None,
        cv_issue_id=cv_issue_id,
    )


def _outcome(*entries, skipped=(), degraded=False, reason=None) -> PullFetchOutcome:
    weeks = (
        ()
        if degraded
        else (PullWeekResult(week=WEEK, year=YEAR, entries=tuple(entries)),)
    )
    return PullFetchOutcome(
        weeks=weeks, skipped=tuple(skipped), degraded=degraded, outage_reason=reason
    )


class _FakeClient:
    """Stand-in for :class:`PullSourceClient` returning a prepared outcome."""

    def __init__(self, outcome: PullFetchOutcome) -> None:
        self._outcome = outcome
        self.calls: list = []

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def aclose(self) -> None:  # pragma: no cover - context manager path used
        return None

    async def fetch_weeks(self, weeks):
        self.calls.append(list(weeks))
        return self._outcome


def _install_client(monkeypatch, outcome: PullFetchOutcome | None) -> dict:
    """Route the handler's fetch at a stub; return a marker dict recording use."""
    marker: dict = {"client": None, "factory_built": False}

    def _fake_factory(settings):
        marker["factory_built"] = True
        return object()

    def _fake_ctor(factory, url, **kwargs):
        client = _FakeClient(outcome)  # type: ignore[arg-type]
        marker["client"] = client
        marker["url"] = url
        return client

    monkeypatch.setattr(pull_commands, "make_pull_factory", _fake_factory)
    monkeypatch.setattr(pull_commands, "PullSourceClient", _fake_ctor)
    return marker


async def _ctx(db, settings: Settings) -> tuple[HandlerContext, CommandService]:
    """A NON-started CommandService (its context enqueues without executing)."""
    svc = CommandService(db, settings)
    return svc.context, svc


async def _refresh_series_rows(db) -> list[CommandRow]:
    async with db.read_session() as session:
        return list(
            (
                await session.execute(
                    select(CommandRow).where(CommandRow.name == "refresh-series")
                )
            )
            .scalars()
            .all()
        )


def _settings(config_dir, **over) -> Settings:
    base = dict(pull_enabled=True, pull_source_url="https://pull.example/x")
    base.update(over)
    return Settings(config_dir=config_dir, **base)


# --- FRG-PULL-005: refresh trigger -------------------------------------------


@pytest.mark.req("FRG-PULL-005")
async def test_matched_but_missing_enqueues_one_deduplicated_refresh(
    db, tmp_path, config_dir, command_registry, monkeypatch
):
    """Full pipeline: two matched-but-missing entries for one watched series →
    the week is stored, matched, and exactly ONE deduplicated ``refresh-series``
    is enqueued for the series — with no issue status written by the pull side."""
    series_id, issue_id = await seed_series_issue(db, tmp_path)
    day = dt.date(2026, 7, 8)
    marker = _install_client(
        monkeypatch,
        _outcome(_entry("Spawn", "2", day=day), _entry("Spawn", "3", day=day)),
    )
    ctx, _svc = await _ctx(db, _settings(config_dir))

    summary = await _handle_pull_refresh(PullRefreshCommand(), ctx)

    # The week was stored (replace-on-refresh) and both entries persisted.
    async with db.read_session() as session:
        stored = await repo.list_week(session, WEEK_KEY)
    assert len(stored) == 2
    # Both entries matched the series but no issue exists yet → link is None,
    # match_type is the confident name_seq — NO status field exists on the row.
    assert {r.match_type for r in stored} == {"name_seq"}
    assert all(r.matched_issue_id is None for r in stored)
    assert not any(hasattr(r, "status") for r in stored)

    # Exactly one refresh-series for the one series (dedup within the run).
    rows = await _refresh_series_rows(db)
    assert len(rows) == 1
    assert rows[0].payload_hash  # a real queued command
    assert rows[0].triggered_by == "pull-refresh"
    import json

    assert json.loads(rows[0].payload)["series_id"] == series_id
    assert "1 refresh-series enqueued" in summary

    # The pull side wrote NOTHING to the issue (D4): it stays as seeded.
    async with db.read_session() as session:
        from foragerr.library.models import IssueRow

        issue = await session.get(IssueRow, issue_id)
    assert issue is not None and issue.monitored is True


@pytest.mark.req("FRG-PULL-005")
async def test_refresh_series_deduplicated_across_runs(
    db, tmp_path, config_dir, command_registry, monkeypatch
):
    """A second pull run for the same missing series does not enqueue a second
    ``refresh-series`` while the first is still queued (FRG-SCHED-003 dedup)."""
    await seed_series_issue(db, tmp_path)
    day = dt.date(2026, 7, 8)
    _install_client(monkeypatch, _outcome(_entry("Spawn", "2", day=day)))
    ctx, _svc = await _ctx(db, _settings(config_dir))

    await _handle_pull_refresh(PullRefreshCommand(), ctx)
    await _handle_pull_refresh(PullRefreshCommand(), ctx)

    assert len(await _refresh_series_rows(db)) == 1


@pytest.mark.req("FRG-PULL-005")
async def test_present_matched_issue_triggers_no_refresh(
    db, tmp_path, config_dir, command_registry, monkeypatch
):
    """A pull entry whose matched issue already exists locally records the link
    and enqueues NO refresh-series (steady-state weeks do not churn refreshes)."""
    await seed_series_issue(db, tmp_path)  # Spawn #1 exists (cv_issue_id 123456)
    # Present issue → an id match (the high-confidence path, independent of the
    # week window); it resolves to the existing local issue, so no refresh fires.
    _install_client(
        monkeypatch,
        _outcome(_entry("Spawn", "1", day=dt.date(2026, 7, 8), cv_issue_id=123456)),
    )
    ctx, _svc = await _ctx(db, _settings(config_dir))

    summary = await _handle_pull_refresh(PullRefreshCommand(), ctx)

    async with db.read_session() as session:
        stored = await repo.list_week(session, WEEK_KEY)
    assert len(stored) == 1 and stored[0].matched_issue_id is not None
    assert await _refresh_series_rows(db) == []
    assert "0 refresh-series enqueued" in summary


# --- FRG-PULL-006: enabled-gate, degraded, config, schedule, throttle --------


@pytest.mark.req("FRG-PULL-006")
async def test_disabled_gate_noops_without_fetching(
    db, config_dir, command_registry, monkeypatch
):
    """pull_enabled=false: the handler no-ops cleanly, issuing no fetch."""
    marker = _install_client(monkeypatch, _outcome())
    ctx, _svc = await _ctx(db, _settings(config_dir, pull_enabled=False))

    summary = await _handle_pull_refresh(PullRefreshCommand(), ctx)

    assert "disabled" in summary
    assert marker["client"] is None  # the client was never constructed/called
    assert marker["factory_built"] is False


@pytest.mark.req("FRG-PULL-006")
async def test_empty_source_url_noops_without_fetching(
    db, config_dir, command_registry, monkeypatch
):
    marker = _install_client(monkeypatch, _outcome())
    ctx, _svc = await _ctx(db, _settings(config_dir, pull_source_url=""))

    summary = await _handle_pull_refresh(PullRefreshCommand(), ctx)

    assert "no pull_source_url" in summary
    assert marker["client"] is None


@pytest.mark.req("FRG-PULL-006")
@pytest.mark.req("FRG-PULL-002")
async def test_degraded_run_stores_nothing_and_leaves_prior_week_intact(
    db, tmp_path, config_dir, command_registry, monkeypatch
):
    """A degraded fetch stores nothing, leaves the previously stored week intact,
    and completes with a note (no crash)."""
    await seed_series_issue(db, tmp_path)
    # Prior successful week already on disk (byte-for-byte baseline).
    async with db.write_session() as session:
        await repo.replace_week(
            session, WEEK_KEY, [_entry("Spawn", "2", day=dt.date(2026, 7, 8))]
        )
    async with db.read_session() as session:
        before = await repo.list_week(session, WEEK_KEY)

    _install_client(monkeypatch, _outcome(degraded=True, reason="backend-down"))
    ctx, _svc = await _ctx(db, _settings(config_dir))

    summary = await _handle_pull_refresh(PullRefreshCommand(), ctx)

    assert "degraded" in summary and "backend-down" in summary
    async with db.read_session() as session:
        after = await repo.list_week(session, WEEK_KEY)
    assert [r.id for r in after] == [r.id for r in before]  # untouched
    assert [r.fetched_at for r in after] == [r.fetched_at for r in before]
    assert await _refresh_series_rows(db) == []


@pytest.mark.req("FRG-PULL-006")
async def test_config_keys_defaults_and_documented_rendering(config_dir):
    """The three pull config keys carry the owner-decided defaults and are
    rendered with their documentation into config.yaml (FRG-NFR-009)."""
    settings = Settings(config_dir=config_dir)
    assert settings.pull_enabled is False
    assert settings.pull_source_url.startswith("https://walksoftly")
    assert settings.pull_refresh_interval_seconds == 14400

    body = render_documented_config()
    assert "pull_enabled:" in body
    assert "pull_source_url:" in body
    assert "pull_refresh_interval_seconds:" in body
    # The documentation comment is emitted, not just the value.
    assert "opt-in optional" in body


@pytest.mark.req("FRG-PULL-006")
async def test_sub_minimum_interval_is_clamped_at_registration(db, config_dir):
    """A configured interval below the documented 1 h floor is clamped UP by
    register_task (raised, logged) — the source is never polled faster."""
    svc = CommandService(db)
    scheduler = IntervalScheduler(db, svc, tick_seconds=5)
    settings = _settings(config_dir, pull_refresh_interval_seconds=600)

    await register_pull_refresh_task(scheduler, settings)

    definition = scheduler.task_definition(PULL_REFRESH_TASK)
    assert definition.interval_seconds == PULL_REFRESH_MIN_INTERVAL_SECONDS == 3600
    assert PULL_REFRESH_TASK in scheduler.task_names()


@pytest.mark.req("FRG-PULL-006")
async def test_task_registration_uses_configured_interval(config_dir):
    settings = _settings(config_dir, pull_refresh_interval_seconds=7200)
    reg = pull_refresh_task_registration(settings)
    assert reg == {
        "name": "pull-refresh",
        "command_name": "pull-refresh",
        "interval_seconds": 7200,
        "min_interval_seconds": 3600,
    }


@pytest.mark.req("FRG-PULL-006")
async def test_scheduled_tick_is_throttled_within_the_interval_but_force_run_bypasses(
    db, config_dir, command_registry
):
    """The scheduler interval gate IS the re-poll throttle: a scheduled tick
    within the window enqueues nothing, while a manual force-run bypasses it and
    enqueues immediately (FRG-PULL-006 'suppresses only scheduled fetches')."""
    svc = CommandService(db, _settings(config_dir))  # NOT started: nothing executes
    scheduler = IntervalScheduler(db, svc, tick_seconds=5)
    await register_pull_refresh_task(
        scheduler, _settings(config_dir, pull_refresh_interval_seconds=10000)
    )

    t0 = dt.datetime(2026, 7, 6, 12, 0, 0)
    first = await scheduler.tick(now=t0)
    assert [r.name for r in first] == ["pull-refresh"]  # due (never run before)

    # Retire the queued command so dedup cannot mask the throttle/force behaviour.
    async with db.write_session() as session:
        row = await session.get(CommandRow, first[0].id)
        row.status = "completed"

    # A tick well within the interval window enqueues nothing — throttled.
    within = await scheduler.tick(now=t0 + dt.timedelta(seconds=30))
    assert within == []

    # A manual force-run bypasses the gate and enqueues a NEW command now.
    forced = await scheduler.force_run(PULL_REFRESH_TASK)
    assert forced.id != first[0].id
    assert forced.status == "queued"


@pytest.mark.req("FRG-PULL-006")
def test_fetch_weeks_are_current_and_previous_iso_weeks():
    """A run fetches the current + previous release weeks (FRG-PULL-002)."""
    weeks = _fetch_weeks(as_of=dt.date(2026, 7, 8))  # ISO 2026-W28
    assert weeks == [(28, 2026), (27, 2026)]
