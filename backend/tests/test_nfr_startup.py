"""FRG-NFR-001 — startup time budget, no-outbound-at-startup guard, and the
flows/importer isolated-importability regression guard.

Three properties homed on the startup requirement (see the m2-hardening-performance
delta and design):

1. **Isolated-importability regression guard** (always-on, cheap): every importer
   and library-flows leaf module — plus the ``foragerr.downloads`` package — must
   import cleanly as the *sole* entry point in a fresh subprocess. A re-opened
   eager import cycle across the flows/importer/downloads seam surfaces here as a
   startup ``ImportError`` rather than only in a scoped test run. The module list
   is *discovered* (walked) rather than hand-maintained so a new leaf is covered
   automatically; the delta's explicitly-named modules are unioned in as a floor.

2. **Startup never blocks on an outbound network call** (always-on, cheap): with
   ComicVine configured, the app reaches ready-to-serve without any startup hook
   issuing or awaiting an outbound request through the shared HTTP factory — the
   factory's network choke point is patched to fail loudly if touched.

3. **Ready-to-serve within the startup budget** (soak/perf, env-gated): against a
   seeded 5,000-issue database already at the head schema (migrations excluded),
   each start reaches ready-to-serve — root ``/health`` 200 **and** the scheduler
   running — within 15 s at p95 over N starts.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import importlib
import os
import pkgutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from foragerr.config import Settings

# --- startup budget constants (from the FRG-NFR-001 delta) -------------------

STARTUP_BUDGET_SECONDS = 15.0
SEEDED_ISSUE_COUNT = 5_000
SEEDED_SERIES_COUNT = 200  # ~25 issues/series → 5,000 issues
STARTUP_SAMPLES = 5  # N starts for the p95

_SOAK = pytest.mark.skipif(
    os.environ.get("FORAGERR_RUN_SOAK") != "1",
    reason="startup-budget soak gated on FORAGERR_RUN_SOAK=1 (timed 5k-issue starts)",
)


# --- isolated-importability regression guard (task 3.1c) ---------------------

#: The delta names these explicitly; kept as a floor so discovery drift can never
#: silently drop a load-bearing module from the guard.
_NAMED_LEAF_MODULES = (
    "foragerr.importer",
    "foragerr.importer.pipeline",
    "foragerr.importer.sources",
    "foragerr.library.flows",
    "foragerr.library.flows.library_import",
    "foragerr.library.flows.rename",
    "foragerr.library.flows.rescan",
    "foragerr.downloads",
)


def _discover_leaf_modules() -> list[str]:
    """Every submodule under ``foragerr.importer`` and ``foragerr.library.flows``
    (recursively), unioned with the delta's explicitly-named modules and the
    ``foragerr.downloads`` package.

    Discovery keeps the guard from going stale: a newly added importer/flows leaf
    is covered without editing this list. Walking imports the *packages* in THIS
    interpreter only to read their ``__path__``; the actual isolation check runs
    each module in a fresh subprocess below.
    """
    names: set[str] = set(_NAMED_LEAF_MODULES)
    for pkg_name in ("foragerr.importer", "foragerr.library.flows"):
        pkg = importlib.import_module(pkg_name)
        for info in pkgutil.walk_packages(pkg.__path__, pkg_name + "."):
            names.add(info.name)
    return sorted(names)


@pytest.mark.req("FRG-NFR-001")
@pytest.mark.parametrize("module", _discover_leaf_modules())
def test_leaf_module_imports_as_sole_entry_point(module: str) -> None:
    """Import ``module`` as the first and only import in a fresh interpreter.

    No other module has primed ``sys.modules``, so a re-introduced eager cycle
    across the flows/importer/downloads seam (e.g. a top-level
    ``foragerr.downloads`` import re-added to ``importer/sources.py``) fails here
    with a circular-import ``ImportError`` instead of passing on the back of an
    already-warm module graph.
    """
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"`import {module}` failed as the sole entry point in a fresh interpreter "
        f"(a re-opened import cycle?):\n{result.stderr}"
    )


# --- seeding helper ----------------------------------------------------------


async def _seed_issues(config_dir: Path, *, series_count: int, issue_count: int) -> None:
    """Prepare a head-schema DB under ``config_dir`` and seed it with
    ``issue_count`` issues spread across ``series_count`` series (one root folder).

    Runs in the test's setup phase only — never inside the measured window. Rows
    are added in a single write transaction to keep seeding fast.
    """
    from sqlalchemy import select, text

    from foragerr.creators.commands import BACKFILL_MARKER_KEY
    from foragerr.db import Database, prepare_database
    from foragerr.db.first_run import APP_STATE_TABLE
    from foragerr.library.models import IssueRow, RootFolderRow, SeriesRow
    from foragerr.library.ordering import ordering_key_for
    from foragerr.parser.normalize import matching_key
    from foragerr.quality.models import DEFAULT_PROFILE_NAME, FormatProfileRow

    prepare_database(config_dir)
    db = Database(db_path=config_dir / "foragerr.db")
    try:
        async with db.read_session() as session:
            profile_id = (
                await session.execute(
                    select(FormatProfileRow.id).where(
                        FormatProfileRow.name == DEFAULT_PROFILE_NAME
                    )
                )
            ).scalar_one()

        now = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
        per_series = max(1, issue_count // series_count)
        async with db.write_session() as session:
            root = RootFolderRow(path=str(config_dir / "library"))
            session.add(root)
            await session.flush()

            cv_issue = 1
            issues_left = issue_count
            for s in range(series_count):
                if issues_left <= 0:
                    break
                title = f"Seed Series {s:04d}"
                series = SeriesRow(
                    cv_volume_id=100_000 + s,
                    title=title,
                    sort_title=title,
                    matching_key=matching_key(title),
                    start_year=2000 + (s % 25),
                    status="continuing",
                    monitored=True,
                    monitor_new_items="all",
                    format_profile_id=profile_id,
                    root_folder_id=root.id,
                    path=str(config_dir / "library" / f"series-{s:04d}"),
                    added_at=now,
                )
                session.add(series)
                await session.flush()  # assign series.id
                for n in range(min(per_series, issues_left)):
                    number = str(n + 1)
                    session.add(
                        IssueRow(
                            series_id=series.id,
                            cv_issue_id=cv_issue,
                            issue_number=number,
                            ordering_key=ordering_key_for(number),
                            cover_date=dt.date(2000 + (s % 25), 1, 1),
                            issue_type="regular",
                            monitored=True,
                            added_at=now,
                        )
                    )
                    cv_issue += 1
                    issues_left -= 1
        # Mark the one-time credits backfill (FRG-CRTR-003) as already done for
        # this seeded library. The backfill is a marker-gated startup hook that,
        # on an as-yet-unbackfilled non-empty library, enqueues deduplicated
        # refresh-series that a worker later runs — a legitimate, queue-driven
        # (post-startup, NOT startup-hook) ComicVine trigger, covered by
        # tests/creators/test_backfill.py. Setting the marker keeps THIS guard
        # focused on its actual invariant (no startup HOOK touches outbound) and
        # the budget soak on pure startup cost, rather than the one-time backfill.
        async with db.write_session() as session:
            await session.execute(
                text(
                    f"INSERT INTO {APP_STATE_TABLE} (key, value) VALUES (:k, 'done')"
                ),
                {"k": BACKFILL_MARKER_KEY},
            )
    finally:
        await db.close()


# --- no-outbound-at-startup guard (task 3.1b) --------------------------------


@pytest.mark.req("FRG-NFR-001")
def test_startup_issues_no_outbound_http_via_shared_factory(tmp_path, monkeypatch):
    """With ComicVine configured, the app reaches ready-to-serve without any
    startup hook awaiting an outbound request through the shared HTTP factory.

    The factory's redirect-walking network choke point (``OutboundClient._open_final``,
    the single method behind get/post/request/stream) is patched to fail loudly.
    Any startup hook that awaited outbound would abort startup — so a clean
    ready-to-serve is the enforcement of "startup must not block on any outbound
    network call" (the load-bearing FRG-NFR-001 sub-rule).
    """
    from foragerr.http import factory as factory_module

    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    # Seed a tiny DB — the guard is about outbound behavior, not scale.
    asyncio.run(_seed_issues(config_dir, series_count=2, issue_count=4))

    calls: list[str] = []

    async def _blocked_open_final(self, method, url, **kwargs):
        calls.append(f"{method} {url}")
        raise AssertionError(
            "outbound HTTP issued through the shared factory during startup "
            "(FRG-NFR-001: startup must not block on any outbound network call)"
        )

    monkeypatch.setattr(
        factory_module.OutboundClient, "_open_final", _blocked_open_final
    )

    # Configured-but-unreachable integration: a ComicVine key is present so the
    # integration is "configured"; the patched factory stands in for the
    # unreachable network — a startup hook touching it would raise.
    settings = Settings(config_dir=config_dir, comicvine_api_key="0" * 40)
    from foragerr.app import create_app

    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200, response.text
        assert app.state.scheduler is not None

    assert calls == [], f"startup issued outbound HTTP: {calls}"


# --- ready-to-serve within the startup budget (task 3.1a, soak/perf) ---------


@_SOAK
@pytest.mark.req("FRG-NFR-001")
def test_ready_to_serve_within_startup_budget(tmp_path):
    """Timed ready-to-serve against a seeded 5,000-issue DB already at head
    schema: root ``/health`` 200 **and** the scheduler running within 15 s at p95
    over N starts, excluding one-time migrations (the DB is pre-migrated so each
    measured start only opens the engine + boots the scheduler).
    """
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    asyncio.run(
        _seed_issues(
            config_dir,
            series_count=SEEDED_SERIES_COUNT,
            issue_count=SEEDED_ISSUE_COUNT,
        )
    )
    settings = Settings(config_dir=config_dir)
    from foragerr.app import create_app

    durations: list[float] = []
    for _ in range(STARTUP_SAMPLES):
        app = create_app(settings)
        start = time.monotonic()
        with TestClient(app) as client:  # entering runs the full startup lifespan
            response = client.get("/health")
            elapsed = time.monotonic() - start
            assert response.status_code == 200, response.text
            assert app.state.scheduler is not None
        durations.append(elapsed)

    durations.sort()
    # p95 over the samples (nearest-rank; with 5 samples this is the max).
    rank = max(0, int(round(0.95 * len(durations) + 0.5)) - 1)
    p95 = durations[min(rank, len(durations) - 1)]
    assert p95 < STARTUP_BUDGET_SECONDS, (
        f"startup p95 {p95:.2f}s exceeded the {STARTUP_BUDGET_SECONDS:.0f}s budget "
        f"(samples={['%.2f' % d for d in durations]})"
    )
