"""The health-aggregation service: per-component view + warnings subset
(FRG-NFR-011)."""

from __future__ import annotations

import asyncio
import datetime as dt
import os
import time
from collections import deque
from types import SimpleNamespace

import pytest

from foragerr.config import Settings
from foragerr.db import DB_FILENAME
from foragerr.db.backup import write_scheduled_backup
from foragerr.db.backup_command import quick_check_startup_hook
from foragerr.downloads.models import DownloadClientRow
from foragerr.health import HealthService
from foragerr.health import service as health_service
from foragerr.health.service import BACKUP_OVERDUE_INTERVAL_MULTIPLE
from foragerr.health.state import record_integrity, reset_integrity
from foragerr.indexers.models import IndexerRow
from foragerr.library.models import RootFolderRow
from foragerr.metadata import ratelimit
from foragerr.providers.backoff import PROVIDER_INDEXER, ProviderBackoff


@pytest.fixture(autouse=True)
def _isolate_health():
    reset_integrity()
    ratelimit.reset_gate()
    yield
    reset_integrity()
    ratelimit.reset_gate()


def _settings(db) -> Settings:
    return Settings(config_dir=db.db_path.parent)


class _StubScheduler:
    async def status(self):
        return []


def _service(db, **kw) -> HealthService:
    return HealthService(db, _settings(db), scheduler=_StubScheduler(), **kw)


async def _add_indexer(db, name: str = "DogNZB") -> int:
    async with db.write_session() as session:
        row = IndexerRow(
            name=name,
            implementation="newznab",
            protocol="usenet",
            priority=25,
            enabled=True,
            enable_rss=True,
            enable_auto=True,
            enable_interactive=True,
            settings="{}",
            added_at=dt.datetime(2026, 1, 1),
        )
        session.add(row)
        await session.flush()
        return row.id


async def _add_client(db, *, name: str, implementation: str) -> int:
    async with db.write_session() as session:
        row = DownloadClientRow(
            name=name,
            implementation=implementation,
            protocol="ddl" if implementation == "ddl" else "usenet",
            priority=25,
            enabled=True,
            remove_completed_downloads=True,
            settings="{}",
            added_at=dt.datetime(2026, 1, 1),
        )
        session.add(row)
        await session.flush()
        return row.id


def _by_component(components):
    return {c.component: c for c in components}


@pytest.mark.req("FRG-META-016")
async def test_comicvine_budget_exhaustion_surfaces_as_degraded(db):
    """An exhausted per-path budget surfaces the ComicVine component as degraded
    with a budget message (a deferral is never silent), even though the gate's
    rate-limit degraded/back-off flag stays OFF."""
    from foragerr.metadata.errors import ComicVineBudgetExhausted

    gate = ratelimit.gate()
    budget = 2
    for _ in range(budget):
        await gate.acquire(0.0, bucket="issue", budget=budget)
    with pytest.raises(ComicVineBudgetExhausted):
        await gate.acquire(0.0, bucket="issue", budget=budget)

    service = _service(db)
    comp = _by_component(await service.component_view())["comicvine"]
    assert comp.state == "degraded"
    message = (comp.message or "").lower()
    assert "budget" in message and "issue" in message
    # And it shows up in the actionable warnings list.
    assert "comicvine" in {w.source for w in await service.warnings()}


# --- ComicVine budget: approaching the ceiling + the meter's numbers ---------
# (MODIFIED FRG-META-016 / FRG-API-025, m11-cv-budget)


def _cv_health(**overrides):
    """A ``comicvine_health()``-shaped payload with everything quiet by default."""
    payload = {
        "degraded": False,
        "cooldown_remaining_seconds": 0.0,
        "path_budgets": {},
        "budget_exhausted": False,
        "auth_failed": False,
    }
    payload.update(overrides)
    return payload


def _bucket(used: int, ceiling: int = 10, **overrides):
    """One gate-shaped bucket entry. ``approaching`` defaults the way the gate
    computes it (>=80% of the ceiling) rather than to a constant, so a caller
    that wants the batch-paused-but-not-approaching case simply passes a low
    ``used`` and gets an honest payload."""
    info = {
        "used": used,
        "ceiling": ceiling,
        "batch_used": min(used, 7),
        "batch_ceiling": 7,
        "approaching": used >= ceiling * ratelimit.BUDGET_WARNING_FRACTION,
        "resumes_in_seconds": 0.0,
        "batch_resumes_in_seconds": 0.0,
    }
    info.update(overrides)
    return info


@pytest.mark.req("FRG-META-016")
async def test_comicvine_approaching_ceiling_warns_before_the_wall_and_clears(db):
    """Crossing the warning fraction surfaces a DISTINCT approaching-limit state
    — naming the bucket, its usage against the ceiling, and the lane that pauses
    first — while requests are still being admitted, and it clears itself when
    the window rolls (the component is a pure render of the gate: no state to
    reset, no operator action)."""
    gate = ratelimit.gate()
    budget = 10
    # Interactive admissions climb past the batch share (0.7 -> 7) without being
    # refused, so the bucket reaches 80% with NOTHING exhausted (FRG-META-022).
    for _ in range(8):
        await gate.acquire(
            0.0, bucket="issue", budget=budget, lane="interactive", batch_share=0.7
        )

    service = _service(db)
    comp = _by_component(await service.component_view())["comicvine"]
    assert comp.state == "degraded"
    message = comp.message or ""
    assert "approaching" in message.lower()
    assert "issue" in message and "8/10" in message  # bucket + usage/ceiling
    assert "batch" in message.lower()  # the lane that pauses first is named
    assert "exhausted" not in message.lower()  # nothing has been refused
    assert "comicvine" in {w.source for w in await service.warnings()}

    # The window rolls: every admission ages out and the warning goes away.
    old = asyncio.get_running_loop().time() - ratelimit.BUDGET_WINDOW_SECONDS - 1.0
    gate._ledgers["issue"] = deque([old] * 8)
    comp = _by_component(await service.component_view())["comicvine"]
    assert comp.state == "ok"
    assert comp.detail is None
    assert "comicvine" not in {w.source for w in await service.warnings()}


@pytest.mark.req("FRG-META-016")
@pytest.mark.req("FRG-META-022")
async def test_approaching_warning_names_the_paused_batch_lane(db):
    """When the batch share is spent but the interactive reserve remains, the
    warning says exactly that — the operator learns what stopped (background
    work) and what still works (their own searches), not just a number."""
    gate = ratelimit.gate()
    budget = 10
    for _ in range(7):  # the whole batch share (floor(10 * 0.7))
        await gate.acquire(
            0.0, bucket="issue", budget=budget, lane="batch", batch_share=0.7
        )
    await gate.acquire(  # ... and one admission from the reserve
        0.0, bucket="issue", budget=budget, lane="interactive", batch_share=0.7
    )

    comp = _by_component(await _service(db).component_view())["comicvine"]
    message = (comp.message or "").lower()
    assert comp.state == "degraded"
    assert "paused" in message and "batch" in message
    assert "reserve" in message


@pytest.mark.req("FRG-META-016")
@pytest.mark.req("FRG-META-022")
async def test_a_paused_batch_lane_alone_does_not_degrade_health(db):
    """The gate reports a bucket the moment its BATCH lane pauses, which at the
    defaults happens at 70% — below the 80% warning fraction. That is the normal
    end-state of a nightly enrichment run, not a warning: Health stays ok, and
    the meter still gets the numbers.

    Inferring "approaching" from payload membership got both halves of the
    message wrong at once — it claimed a bucket at 105/150 was approaching its
    ceiling, and told the operator "nothing is refused yet" while background work
    was being refused."""
    gate = ratelimit.gate()
    budget = 10  # batch ceiling 7, warning threshold 8
    for _ in range(7):
        await gate.acquire(
            0.0, bucket="issue", budget=budget, lane="batch", batch_share=0.7
        )

    service = _service(db)
    comp = _by_component(await service.component_view())["comicvine"]
    assert comp.state == "ok"
    assert comp.message is None
    assert "comicvine" not in {w.source for w in await service.warnings()}
    # ... but the meter still renders it, with the paused lane's own countdown.
    bucket = (comp.detail or {})["buckets"][0]
    assert bucket["bucket"] == "issue"
    assert bucket["approaching"] is False
    assert bucket["batch_used"] == 7 and bucket["batch_ceiling"] == 7
    assert bucket["batch_resume_seconds"] > 0  # a pause always says "until when"
    assert bucket["resume_seconds"] == 0.0  # the PATH is nowhere near its wall


@pytest.mark.req("FRG-META-016")
@pytest.mark.req("FRG-META-022")
async def test_at_the_warning_fraction_the_approaching_state_returns(db):
    """The boundary the previous test's bucket has not reached: one more
    admission takes usage to the fraction itself and the warning appears."""
    gate = ratelimit.gate()
    budget = 10
    for _ in range(7):
        await gate.acquire(
            0.0, bucket="issue", budget=budget, lane="batch", batch_share=0.7
        )
    await gate.acquire(  # 8/10 == the 80% threshold
        0.0, bucket="issue", budget=budget, lane="interactive", batch_share=0.7
    )

    comp = _by_component(await _service(db).component_view())["comicvine"]
    assert comp.state == "degraded"
    assert "approaching" in (comp.message or "").lower()
    assert (comp.detail or {})["buckets"][0]["approaching"] is True


@pytest.mark.req("FRG-META-016")
@pytest.mark.req("FRG-META-022")
async def test_the_approaching_remediation_never_denies_a_pause_in_progress(
    db, monkeypatch
):
    """"Nothing is refused yet" is the right thing to say only while nothing is.
    Once the batch lane is spent, background work IS being deferred, and a
    remediation that says otherwise sends the operator looking for a fault that
    is not there."""
    monkeypatch.setattr(
        health_service,
        "comicvine_health",
        lambda: _cv_health(path_budgets={"issue": _bucket(9, batch_used=7)}),
    )
    comp = _by_component(await _service(db).component_view())["comicvine"]
    remediation = (comp.remediation or "").lower()
    assert "nothing is refused yet" not in remediation
    assert "already being deferred" in remediation
    assert "interactive" in remediation  # ...and what still works

    # While batch still has room, the reassurance is accurate and stays.
    monkeypatch.setattr(
        health_service,
        "comicvine_health",
        lambda: _cv_health(path_budgets={"issue": _bucket(9, batch_used=2)}),
    )
    comp = _by_component(await _service(db).component_view())["comicvine"]
    assert "nothing is refused yet" in (comp.remediation or "").lower()


@pytest.mark.req("FRG-META-016")
@pytest.mark.req("FRG-META-019")
async def test_comicvine_state_precedence_is_pinned(db, monkeypatch):
    """The four ComicVine dimensions are independent, so their PRECEDENCE into
    the single state/message slot is a decision worth pinning: auth (nothing
    works) > 429 back-off (ComicVine is pushing back) > budget exhausted
    (refusals are happening) > approaching (they are about to) > ok. Each case
    below carries the signals of every LOWER-priority one too, so a regression
    that reorders them fails here."""
    approaching = {"issue": _bucket(8)}
    exhausted = {"issue": _bucket(10, resumes_in_seconds=120.0)}
    cases = [
        (
            _cv_health(
                auth_failed=True,
                degraded=True,
                cooldown_remaining_seconds=30.0,
                budget_exhausted=True,
                path_budgets=exhausted,
            ),
            "error",
            "key",
        ),
        (
            _cv_health(
                degraded=True,
                cooldown_remaining_seconds=30.0,
                budget_exhausted=True,
                path_budgets=exhausted,
            ),
            "degraded",
            "rate-limited",
        ),
        (
            _cv_health(budget_exhausted=True, path_budgets=exhausted),
            "degraded",
            "exhausted",
        ),
        (_cv_health(path_budgets=approaching), "degraded", "approaching"),
        (_cv_health(), "ok", None),
    ]
    service = _service(db)
    for payload, expected_state, expected_word in cases:
        monkeypatch.setattr(
            health_service, "comicvine_health", lambda payload=payload: payload
        )
        comp = _by_component(await service.component_view())["comicvine"]
        assert comp.state == expected_state, payload
        if expected_word is None:
            assert comp.message is None
        else:
            assert expected_word in (comp.message or "").lower(), payload


@pytest.mark.req("FRG-API-025")
async def test_comicvine_detail_carries_the_meter_numbers_hottest_first(
    db, monkeypatch
):
    """The component carries the structured budget numbers the meter renders
    (FRG-UI-040) — every reported bucket, hottest first, with the lane split and
    resume time — and the flags, whatever state won the message slot."""
    monkeypatch.setattr(
        health_service,
        "comicvine_health",
        lambda: _cv_health(
            budget_exhausted=True,
            path_budgets={
                "volumes": _bucket(9, resumes_in_seconds=0.0),
                "issue": _bucket(10, resumes_in_seconds=240.5),
            },
        ),
    )
    comp = _by_component(await _service(db).component_view())["comicvine"]

    detail = comp.detail
    assert detail is not None
    assert detail["exhausted"] is True and detail["degraded"] is False
    assert [b["bucket"] for b in detail["buckets"]] == ["issue", "volumes"]
    assert detail["buckets"][0] == {
        "bucket": "issue",
        "used": 10,
        "ceiling": 10,
        "batch_used": 7,
        "batch_ceiling": 7,
        "approaching": True,
        "resume_seconds": 240.5,
        "batch_resume_seconds": 0.0,
    }


@pytest.mark.req("FRG-API-025")
async def test_comicvine_detail_is_absent_while_the_budget_is_quiet(db, monkeypatch):
    """Below the warning fraction the gate reports no buckets, so the detail is
    omitted entirely: the common payload is unchanged by this feature and the UI
    has ONE unambiguous "nothing to say" signal rather than an empty meter."""
    monkeypatch.setattr(health_service, "comicvine_health", lambda: _cv_health())
    comp = _by_component(await _service(db).component_view())["comicvine"]
    assert comp.state == "ok"
    assert comp.detail is None


@pytest.mark.req("FRG-API-025")
async def test_comicvine_detail_never_fabricates_missing_lane_figures(
    db, monkeypatch
):
    """A bucket published without lane figures yields nulls, not zeros: a meter
    that invents "0 of 0 batch used" would be worse than one that says nothing.
    The approaching message degrades to its qualitative form for the same
    reason."""
    monkeypatch.setattr(
        health_service,
        "comicvine_health",
        lambda: _cv_health(
            path_budgets={
                "issue": {
                    "used": 8,
                    "ceiling": 10,
                    "approaching": True,
                    "resumes_in_seconds": 0.0,
                }
            }
        ),
    )
    comp = _by_component(await _service(db).component_view())["comicvine"]
    bucket = (comp.detail or {})["buckets"][0]
    assert bucket["batch_used"] is None and bucket["batch_ceiling"] is None
    assert "batch" in (comp.message or "").lower()


@pytest.mark.req("FRG-NFR-011")
async def test_indexer_backoff_shows_degraded_then_recovers(db):
    indexer_id = await _add_indexer(db)
    backoff = ProviderBackoff(db)
    await backoff.record_failure(PROVIDER_INDEXER, indexer_id, reason="auth failed")

    service = _service(db)
    comp = _by_component(await service.component_view())[f"indexer:{indexer_id}"]
    assert comp.state == "degraded"
    assert comp.disabled_until is not None  # its disabled-until time
    assert comp.last_failure is not None  # last-failure time
    warning_sources = {w.source for w in await service.warnings()}
    assert f"indexer:{indexer_id}" in warning_sources

    # Recovery clears it on the next poll without a restart.
    await backoff.record_success(PROVIDER_INDEXER, indexer_id)
    comp2 = _by_component(await service.component_view())[f"indexer:{indexer_id}"]
    assert comp2.state == "ok"


@pytest.mark.req("FRG-NFR-011")
async def test_every_tracked_component_is_represented(db, tmp_path):
    await _add_indexer(db, name="NZBsu")
    await _add_client(db, name="SAB", implementation="sabnzbd")
    await _add_client(db, name="GetComics", implementation="ddl")
    root = tmp_path / "root"
    root.mkdir()
    async with db.write_session() as session:
        session.add(RootFolderRow(path=str(root)))

    components = await _service(db).component_view()
    kinds = {c.kind for c in components}
    assert {
        "comicvine",
        "indexer",
        "download_client",
        "ddl",
        "scheduler",
        "database",
        "root_folder",
        "disk",
    } <= kinds


@pytest.mark.req("FRG-NFR-011")
async def test_warnings_are_exactly_the_non_ok_subset(db):
    indexer_id = await _add_indexer(db)
    await ProviderBackoff(db).record_failure(
        PROVIDER_INDEXER, indexer_id, reason="boom"
    )
    service = _service(db)

    components = await service.component_view()
    warnings = await service.warnings()
    non_ok = [c for c in components if not c.ok]

    assert {w.source for w in warnings} == {c.component for c in non_ok}
    assert len(warnings) == len(non_ok)
    # Every warning derived from a non-ok component carries a remediation hint.
    assert all(w.remediation_hint for w in warnings)


@pytest.mark.req("FRG-NFR-011")
async def test_database_component_reflects_integrity_and_last_backup(db, tmp_path):
    cfg = db.db_path.parent
    service = _service(db)

    # (a) A failed integrity check → database error naming the failure.
    record_integrity(
        ok=False, check="integrity_check", source="pre-backup", detail="disk image malformed"
    )
    comp = _by_component(await service.component_view())["database"]
    assert comp.state == "error"
    assert "malformed" in (comp.message or "")

    # (b) Integrity ok but no scheduled backup yet → overdue/missing warning.
    reset_integrity()
    comp = _by_component(await service.component_view())["database"]
    assert comp.state == "degraded"
    assert "backup" in (comp.message or "").lower()

    # (c) Integrity ok and a fresh scheduled backup → ok.
    (cfg / "config.yaml").write_text("x: 1\n", encoding="utf-8")
    write_scheduled_backup(cfg / DB_FILENAME, cfg / "config.yaml", cfg, retention=7)
    comp = _by_component(await service.component_view())["database"]
    assert comp.state == "ok"


@pytest.mark.req("FRG-NFR-011")
async def test_overdue_scheduled_backup_is_degraded(db):
    """A scheduled backup older than 2× the backup interval is a degraded
    (overdue) warning on the database component."""
    cfg = db.db_path.parent
    (cfg / "config.yaml").write_text("x: 1\n", encoding="utf-8")
    backup = write_scheduled_backup(
        cfg / DB_FILENAME, cfg / "config.yaml", cfg, retention=7
    )
    interval = _settings(db).db_backup_interval_seconds
    old = time.time() - interval * (BACKUP_OVERDUE_INTERVAL_MULTIPLE + 1)
    os.utime(backup, (old, old))

    comp = _by_component(await _service(db).component_view())["database"]
    assert comp.state == "degraded"
    assert "overdue" in (comp.message or "").lower()


@pytest.mark.req("FRG-DB-012")
async def test_clean_check_clears_database_health_error_without_restart(db):
    """A previously-failing integrity reading clears on the next CLEAN check run
    through the real startup hook (not the reset_integrity test hook), with no
    restart — the database component recovers."""
    cfg = db.db_path.parent
    service = _service(db)

    record_integrity(
        ok=False, check="quick_check", source="startup", detail="disk image malformed"
    )
    assert _by_component(await service.component_view())["database"].state == "error"

    # A real clean quick_check via the production hook clears the error.
    app = SimpleNamespace(state=SimpleNamespace(settings=Settings(config_dir=cfg)))
    await quick_check_startup_hook(app)
    (cfg / "config.yaml").write_text("x: 1\n", encoding="utf-8")
    write_scheduled_backup(cfg / DB_FILENAME, cfg / "config.yaml", cfg, retention=7)

    comp = _by_component(await service.component_view())["database"]
    assert comp.state == "ok"  # recovered, no restart


@pytest.mark.req("FRG-NFR-011")
async def test_root_folder_probe_timeout_is_bounded(db, tmp_path, monkeypatch):
    """A wedged mount (a probe that hangs) times out fast: the component reports
    an unreachable/timed-out error and the request returns within the deadline
    rather than hanging (the orphaned probe thread is an inherent, accepted
    leak)."""
    root = tmp_path / "root"
    root.mkdir()
    async with db.write_session() as session:
        session.add(RootFolderRow(path=str(root)))

    monkeypatch.setattr(health_service, "FS_PROBE_TIMEOUT_SECONDS", 0.05)

    def hang(_path):
        time.sleep(1.0)  # far longer than the probe deadline
        return (True, True, 10**12)

    monkeypatch.setattr(HealthService, "_probe_path", staticmethod(hang))

    start = time.monotonic()
    comps = _by_component(await _service(db).component_view())
    elapsed = time.monotonic() - start

    rf = next(c for c in comps.values() if c.kind == "root_folder")
    assert rf.state == "error"
    assert "timed out" in (rf.message or "").lower()
    assert elapsed < 0.8  # bounded well under the 1s hang


@pytest.mark.req("FRG-NFR-011")
async def test_one_failing_check_is_isolated_others_intact(db, monkeypatch):
    """One component producer raising becomes an error-state component instead
    of 500-ing the whole aggregation; the other components still render."""

    async def boom(self):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(HealthService, "_database_component", boom)

    components = await _service(db).component_view()  # does not raise
    comps = _by_component(components)
    assert comps["database"].state == "error"
    assert "health check failed" in (comps["database"].message or "")
    assert comps["comicvine"].state == "ok"  # unaffected component intact


@pytest.mark.req("FRG-META-019")
async def test_comicvine_auth_failure_surfaces_as_error_and_recovers(db):
    """An authentication rejection marks the ComicVine component ERROR with a
    Settings-facing remediation — outranking the politeness dimensions — and
    the next successful request clears it without a restart (M9 finding F1:
    Health said OK while every worker request failed 401)."""
    ratelimit.gate().note_auth_failed()

    service = _service(db)
    comp = _by_component(await service.component_view())["comicvine"]
    assert comp.state == "error"
    assert "key" in (comp.message or "").lower()
    assert "settings" in (comp.remediation or "").lower()
    assert "comicvine" in {w.source for w in await service.warnings()}

    ratelimit.gate().note_auth_ok()
    comp = _by_component(await service.component_view())["comicvine"]
    assert comp.state == "ok"


@pytest.mark.req("FRG-UI-033")
async def test_pull_source_remediation_speaks_ui_language_not_config_keys(db):
    """The weekly-pull-source degraded remediation names UI concepts, not raw
    config-key names (F4: it told a UI user to 'verify pull_source_url')."""
    from foragerr.providers.backoff import PROVIDER_PULL, PULL_PROVIDER_ID

    await ProviderBackoff(db).record_failure(
        PROVIDER_PULL, PULL_PROVIDER_ID, reason="522 origin unreachable"
    )
    components = await _service(db).component_view()
    pull = _by_component(components)["pull-source"]

    remediation = pull.remediation or ""
    # No snake_case config-key jargon leaks into UI-facing copy.
    assert "pull_source_url" not in remediation
    assert "pull_enabled" not in remediation
    # It still names the concept in plain UI terms.
    assert "weekly pull source url" in remediation.lower()
    assert "calendar" in remediation.lower()
