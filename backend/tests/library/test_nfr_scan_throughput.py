"""FRG-NFR-002 — library scan throughput budget + structural guards.

Always-on structural guards pin the non-starvation shape of
``library-import-scan`` (m2-hardening-performance): the command runs on the
``pp`` workload class with no read-blocking exclusivity, the FS-heavy walk and
existence sweep run through the ``offload`` executor (never on the event
loop), and the measured parse/reconcile/stage phase issues no outbound HTTP —
proposal fetches are per-group, capped, and strictly after staging commits.

The 5,000-file / 10-minute throughput benchmark itself is an opt-in perf run
gated on ``FORAGERR_NFR_PERF=1`` (mirroring the ``FORAGERR_DEP_DOCKER`` /
``FORAGERR_CV_LIVE`` gate convention), with a concurrent API smoke asserting
the FRG-NFR-003 latency budget holds while the scan runs.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from pathlib import Path

import pytest
from sqlalchemy import func, select

from flows_support import CV_HOST, FakeCV, flows_settings
from foragerr.http import HttpClientFactory
from foragerr.library import repo
from foragerr.library.flows.library_import import (
    LibraryImportScanCommand,
    scan_library_root,
)
from foragerr.library.models import LibraryImportGroupRow
from http_support import (
    PUBLIC_V4,
    NoConnectTransport,
    RecordingTransport,
    StubResolver,
)

#: Budgets under test (openspec nfr delta, FRG-NFR-002 / FRG-NFR-003).
SCAN_BUDGET_SECONDS = 600.0
SMOKE_P95_BUDGET_SECONDS = 0.5
SEEDED_FILES = 5_000
SEEDED_SERIES = 200

perf_gate = pytest.mark.skipif(
    os.environ.get("FORAGERR_NFR_PERF") != "1",
    reason="NFR perf benchmarks gated on FORAGERR_NFR_PERF=1",
)


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"comicbytes")
    return path


def _p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    index = max(0, -(-len(ordered) * 95 // 100) - 1)  # ceil(0.95 * n) - 1
    return ordered[index]


async def _group_count(db, root_folder_id: int) -> int:
    async with db.read_session() as session:
        return (
            await session.scalar(
                select(func.count())
                .select_from(LibraryImportGroupRow)
                .where(LibraryImportGroupRow.root_folder_id == root_folder_id)
            )
        ) or 0


# --- always-on structural guards ----------------------------------------------


@pytest.mark.req("FRG-NFR-002")
def test_scan_command_declares_pp_workload_and_no_exclusivity():
    """The scan command carries ``workload_class == "pp"`` (never the default
    pool serving interactive work) and takes NO exclusivity group, so it can
    never hold a read-blocking exclusivity while it walks."""
    assert LibraryImportScanCommand.workload_class == "pp"
    assert LibraryImportScanCommand.exclusivity_group is None


@pytest.mark.req("FRG-NFR-002")
async def test_scan_walk_and_existence_sweep_run_through_offload(
    db, root_folder_id, root_folder_path
):
    """The FS-heavy directory walk and the vanished-file existence sweep both
    go through the ``offload`` executor and execute off the calling (event
    loop) thread — a refactor that moves either onto the loop fails here."""
    _touch(root_folder_path / "Saga (2012)" / "Saga 001 (2012).cbz")
    _touch(root_folder_path / "Saga (2012)" / "Saga 002 (2012).cbz")
    _touch(root_folder_path / "Paper Girls" / "Paper Girls 001 (2015).cbz")

    offloaded: list[str] = []
    threads: list[int] = []

    async def recording_offload(fn, /, *args, **kwargs):
        offloaded.append(getattr(fn, "__name__", repr(fn)))

        def instrumented(*a, **k):
            threads.append(threading.get_ident())
            return fn(*a, **k)

        return await asyncio.to_thread(instrumented, *args, **kwargs)

    summary = await scan_library_root(
        db, None, root_folder_id, offload=recording_offload
    )

    assert "groups=2" in summary
    # Both FS-heavy phases went through the offload seam...
    assert "_walk" in offloaded, f"directory walk not offloaded: {offloaded}"
    assert (
        "vanished_file_ids" in offloaded
    ), f"existence sweep not offloaded: {offloaded}"
    # ...and none of the offloaded work ran on the event-loop thread.
    loop_thread = threading.get_ident()
    assert threads and all(t != loop_thread for t in threads)


@pytest.mark.req("FRG-NFR-002")
async def test_scan_measured_phase_attempts_no_outbound_http(
    db, root_folder_id, root_folder_path, tmp_path
):
    """The measured parse/reconcile/stage phase issues no outbound HTTP
    request: with the (separate, capped) ComicVine proposal phase not in play,
    a full scan completes and stages its groups without a single connection
    attempt (the transport fails the test on any)."""
    _touch(root_folder_path / "Saga (2012)" / "Saga 001 (2012).cbz")
    _touch(root_folder_path / "Saga (2012)" / "Saga 002 (2012).cbz")
    _touch(root_folder_path / "Paper Girls" / "Paper Girls 001 (2015).cbz")
    _touch(root_folder_path / "Paper Girls" / "Paper Girls 002 (2015).cbz")

    cfg = tmp_path / "cfg-noconnect"
    cfg.mkdir()
    factory = HttpClientFactory(
        flows_settings(cfg),
        resolver=StubResolver({}),
        transport=NoConnectTransport(),
    )

    summary = await scan_library_root(
        db, None, root_folder_id, factory=factory
    )

    assert "groups=2" in summary
    assert await _group_count(db, root_folder_id) == 2


@pytest.mark.req("FRG-NFR-002")
async def test_scan_proposal_fetches_are_per_group_never_per_file(
    db, root_folder_id, root_folder_path, tmp_path
):
    """The network fetches a scan does issue (the proposal phase) are bounded
    by GROUP count, never file count: 12 files in 3 series produce exactly 3
    ComicVine searches — a per-file fetch regression multiplies this and
    fails here."""
    names = [("Alpha Squad", 2019), ("Beta Force", 2020), ("Gamma Corps", 2021)]
    for name, year in names:
        for n in range(1, 5):  # 4 files per series = 12 files total
            _touch(
                root_folder_path / f"{name} ({year})" / f"{name} {n:03d} ({year}).cbz"
            )

    cfg = tmp_path / "cfg-fakecv"
    cfg.mkdir()
    settings = flows_settings(cfg, comicvine_min_interval_seconds=0.01)
    cv = FakeCV()
    for vid, (name, year) in enumerate(names, start=101):
        cv.volume(vid, name=name, start_year=year)
    transport = RecordingTransport(cv.handler())
    factory = HttpClientFactory(
        settings, resolver=StubResolver({CV_HOST: [PUBLIC_V4]}), transport=transport
    )

    summary = await scan_library_root(
        db, settings, root_folder_id, factory=factory
    )

    assert "groups=3" in summary
    assert len(transport.requests) == 3, (
        "expected one proposal search per group (3), got "
        f"{len(transport.requests)}: {[str(r.url) for r in transport.requests]}"
    )
    assert all("/volumes/" in str(r.url) for r in transport.requests)


# --- opt-in throughput benchmark (FORAGERR_NFR_PERF=1) --------------------------


@perf_gate
@pytest.mark.req("FRG-NFR-002")
async def test_scan_5000_files_completes_within_budget_without_starving_api(
    tmp_path,
):
    """Seeded 5,000-file / ~200-series benchmark: the parse + reconcile +
    stage phase completes under the 10-minute budget (metadata proposal
    fetches excluded, per the requirement) while a concurrent API smoke stays
    within the FRG-NFR-003 latency budget."""
    import httpx

    from foragerr.app import create_app
    from foragerr.config import Settings

    root = tmp_path / "bigroot"
    per_series = SEEDED_FILES // SEEDED_SERIES  # 25
    for k in range(SEEDED_SERIES):
        # Digit-free series names ("Series AA".."Series TJ") parse cleanly.
        name = f"Series {chr(65 + k // 10)}{chr(65 + k % 10)}"
        series_dir = root / f"{name} (2020)"
        series_dir.mkdir(parents=True)
        for n in range(1, per_series + 1):
            (series_dir / f"{name} {n:03d} (2020).cbz").write_bytes(b"comicbytes")

    cfg = tmp_path / "cfg-perf"
    cfg.mkdir()
    app = create_app(Settings(config_dir=cfg))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Auth: attach the bootstrap API key so requests pass the default-deny
            # perimeter (FRG-AUTH-010); the app seeded it at lifespan startup above.
            client.headers["X-Api-Key"] = app.state.bootstrap_api_key
            async with app.state.db.write_session() as session:
                rf = await repo.create_root_folder(session, str(root))
                rf_id = rf.id

            started = time.perf_counter()
            scan_task = asyncio.create_task(
                scan_library_root(
                    app.state.db, None, rf_id, offload=asyncio.to_thread
                )
            )

            # Concurrent interactive smoke: the scan must not starve reads.
            smoke: list[float] = []
            while not scan_task.done() or len(smoke) < 5:
                t0 = time.perf_counter()
                response = await client.get(
                    "/api/v1/series", params={"pageSize": 20}
                )
                smoke.append(time.perf_counter() - t0)
                assert response.status_code == 200
                if scan_task.done() and len(smoke) >= 5:
                    break
                await asyncio.sleep(0.1)

            summary = await scan_task
            elapsed = time.perf_counter() - started

    assert f"groups={SEEDED_SERIES}" in summary, summary
    assert elapsed < SCAN_BUDGET_SECONDS, (
        f"5,000-file scan took {elapsed:.1f}s, budget {SCAN_BUDGET_SECONDS:.0f}s"
    )
    smoke_p95 = _p95(smoke)
    assert smoke_p95 < SMOKE_P95_BUDGET_SECONDS, (
        f"concurrent API smoke p95 {smoke_p95 * 1000:.0f}ms over the "
        f"{SMOKE_P95_BUDGET_SECONDS * 1000:.0f}ms budget ({len(smoke)} samples)"
    )
    print(
        f"\nNFR-002 benchmark: scan of {SEEDED_FILES} files across "
        f"{SEEDED_SERIES} series took {elapsed:.2f}s "
        f"(budget {SCAN_BUDGET_SECONDS:.0f}s); concurrent API smoke p95 "
        f"{smoke_p95 * 1000:.1f}ms over {len(smoke)} samples "
        f"(budget {SMOKE_P95_BUDGET_SECONDS * 1000:.0f}ms)"
    )
