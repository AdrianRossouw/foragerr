"""FRG-NFR-003 — UI read-endpoint latency budget + page-size-cap audit.

Always-on structural guards (m2-hardening-performance) pin the shape the
latency budget relies on:

- every paged endpoint returns the shared paging envelope, never an unbounded
  array, and the server refuses an over-cap ``pageSize`` — the cap is enforced
  as a FastAPI ``Query(..., le=200)`` upper bound whose violation the app's
  validation handler maps to a bounded 400 (a page larger than the cap is
  never served, which is how this codebase realizes the delta's "clamped to
  the server-side cap" rule: reject-at-cap rather than silent clamp);
- an OpenAPI-schema sweep asserts EVERY operation declaring a ``pageSize``
  query parameter carries that bound, so a new endpoint cannot ship uncapped;
- ``SeriesStatistics`` is computed by SQL aggregates in a constant number of
  statements, independent of the series' row count (never a per-row loop).

The p95 < 500 ms load benchmark over the five UI read endpoints against a
seeded 5,000-issue library is an opt-in perf run gated on
``FORAGERR_NFR_PERF=1`` (mirroring the ``FORAGERR_DEP_DOCKER`` /
``FORAGERR_CV_LIVE`` gate convention).
"""

from __future__ import annotations

import datetime as dt
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from sqlalchemy import event

from foragerr.app import create_app
from foragerr.config import Settings
from foragerr.db.base import utcnow
from foragerr.downloads.models import TrackedDownloadRow
from foragerr.importer.history import EVENT_GRABBED, EVENT_IMPORTED
from foragerr.importer.models import ImportHistoryRow
from foragerr.library import repo
from foragerr.library.models import IssueFileRow, IssueRow
from foragerr.library.ordering import ordering_key_for

#: Budgets under test (openspec nfr delta, FRG-NFR-003).
P95_BUDGET_SECONDS = 0.5
PAGE_SIZE_CAP = 200
SEEDED_ISSUES = 5_000
SEEDED_SERIES = 200

perf_gate = pytest.mark.skipif(
    os.environ.get("FORAGERR_NFR_PERF") != "1",
    reason="NFR perf benchmarks gated on FORAGERR_NFR_PERF=1",
)

#: Envelope keys every paged response must carry (api/paging.py shape).
ENVELOPE_KEYS = {"page", "pageSize", "totalRecords", "records"}

#: Every paged read endpoint (the audit enumerates ALL of them, not only the
#: five the latency budget names). Values are the extra required query params.
PAGED_ENDPOINTS: dict[str, dict[str, object]] = {
    "/api/v1/series": {},
    "/api/v1/issues": {"seriesId": None},  # filled with a seeded id
    "/api/v1/queue": {},
    "/api/v1/history": {},
    "/api/v1/wanted/missing": {},
    "/api/v1/blocklist": {},
    "/api/v1/command": {},
    "/api/v1/pull": {},
    "/api/v1/library-import": {"rootFolderId": None},  # filled with a seeded id
}


def _settings(tmp_path: Path) -> Settings:
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    return Settings(config_dir=cfg)


@asynccontextmanager
async def running_app(settings: Settings):
    """A fully started app (lifespan on the CURRENT loop) + ASGI client."""
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield app, client


def _p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    index = max(0, -(-len(ordered) * 95 // 100) - 1)  # ceil(0.95 * n) - 1
    return ordered[index]


async def _format_profile_id(db) -> int:
    from sqlalchemy import select

    from foragerr.quality.models import DEFAULT_PROFILE_NAME, FormatProfileRow

    async with db.read_session() as session:
        return (
            await session.execute(
                select(FormatProfileRow.id).where(
                    FormatProfileRow.name == DEFAULT_PROFILE_NAME
                )
            )
        ).scalar_one()


async def _seed_series(
    db, tmp_path: Path, *, series: int, issues_per_series: int
) -> tuple[list[int], int]:
    """Seed ``series`` series x ``issues_per_series`` issues (files on every
    second issue, past cover dates so the rest derive as wanted). Returns
    ``(series_ids, root_folder_id)``."""
    profile_id = await _format_profile_id(db)
    root = tmp_path / "lib-root"
    root.mkdir(exist_ok=True)
    series_ids: list[int] = []
    now = utcnow()
    async with db.write_session() as session:
        rf = await repo.create_root_folder(session, str(root))
        for s in range(series):
            row = await repo.create_series(
                session,
                cv_volume_id=100_000 + s,
                title=f"Perf Series {s:03d}",
                start_year=2020,
                format_profile_id=profile_id,
                root_folder_id=rf.id,
                path=str(root / f"Perf Series {s:03d}"),
                monitored=True,
            )
            series_ids.append(row.id)
        issue_rows = []
        for s, sid in enumerate(series_ids):
            for n in range(1, issues_per_series + 1):
                issue_rows.append(
                    IssueRow(
                        series_id=sid,
                        cv_issue_id=1_000_000 + s * 1_000 + n,
                        issue_number=str(n),
                        ordering_key=ordering_key_for(str(n)),
                        cover_date=dt.date(2020 + (n % 5), (n % 12) + 1, 1),
                        monitored=True,
                        added_at=now,
                    )
                )
        session.add_all(issue_rows)
        await session.flush()
        session.add_all(
            IssueFileRow(
                issue_id=issue.id,
                path=str(root / f"file-{issue.cv_issue_id}.cbz"),
                size=25_000_000,
                added_at=now,
            )
            for i, issue in enumerate(issue_rows)
            if i % 2 == 0
        )
        return series_ids, rf.id


# --- always-on cap audit ---------------------------------------------------------


@pytest.mark.req("FRG-NFR-003")
def test_every_page_size_param_declares_the_server_cap(tmp_path):
    """OpenAPI sweep: EVERY operation declaring a ``pageSize`` query parameter
    carries an upper bound of exactly the server cap (200) — a new endpoint
    shipping an uncapped (or differently-capped) collection fails here."""
    app = create_app(_settings(tmp_path))
    schema = app.openapi()
    found: dict[str, object] = {}
    for path, operations in schema.get("paths", {}).items():
        for operation in operations.values():
            for param in operation.get("parameters", ()) or ():
                if param.get("name") != "pageSize" or param.get("in") != "query":
                    continue
                found[path] = param.get("schema", {}).get("maximum")

    # The sweep found the full paged surface (guards against a silent rename
    # of the parameter hollowing this audit out)...
    assert set(PAGED_ENDPOINTS) <= set(found), (
        f"paged endpoints missing from the sweep: "
        f"{set(PAGED_ENDPOINTS) - set(found)}"
    )
    # ...and every pageSize parameter is capped at the server cap.
    uncapped = {path: le for path, le in found.items() if le != PAGE_SIZE_CAP}
    assert not uncapped, f"pageSize params without the {PAGE_SIZE_CAP} cap: {uncapped}"


@pytest.mark.req("FRG-NFR-003")
async def test_paged_endpoints_return_envelopes_and_refuse_over_cap(tmp_path):
    """Behavioral audit over every paged endpoint: an at-cap request returns
    the paging envelope (never an unbounded array) with the requested size
    echoed; a request one past the cap is refused (the app's validation
    handler answers a bounded 400) so a page larger than the server cap is
    never served."""
    async with running_app(_settings(tmp_path)) as (app, client):
        series_ids, root_folder_id = await _seed_series(
            app.state.db, tmp_path, series=2, issues_per_series=3
        )
        for path, extra in PAGED_ENDPOINTS.items():
            params = dict(extra)
            if "seriesId" in params:
                params["seriesId"] = series_ids[0]
            if "rootFolderId" in params:
                params["rootFolderId"] = root_folder_id

            at_cap = await client.get(
                path, params={**params, "pageSize": PAGE_SIZE_CAP}
            )
            assert at_cap.status_code == 200, (
                f"{path} rejected an at-cap pageSize: {at_cap.status_code} "
                f"{at_cap.text}"
            )
            body = at_cap.json()
            assert isinstance(body, dict) and ENVELOPE_KEYS <= set(body), (
                f"{path} did not return a paging envelope: {type(body)} "
                f"{sorted(body) if isinstance(body, dict) else body}"
            )
            assert body["pageSize"] == PAGE_SIZE_CAP
            assert isinstance(body["records"], list)
            assert len(body["records"]) <= PAGE_SIZE_CAP

            over_cap = await client.get(
                path, params={**params, "pageSize": PAGE_SIZE_CAP + 1}
            )
            assert over_cap.status_code == 400, (
                f"{path} served an over-cap pageSize={PAGE_SIZE_CAP + 1}: "
                f"{over_cap.status_code}"
            )


@pytest.mark.req("FRG-NFR-003")
async def test_series_statistics_are_sql_aggregates_with_constant_query_count(
    db, tmp_path
):
    """The have/total stats behind series-list and series-detail come from SQL
    aggregate queries: the statement count is a small constant independent of
    the series' issue/file row count, and every statement aggregates — a
    per-row Python loop (row count-proportional statements, or plain row
    SELECTs) fails here."""
    small_ids, _ = await _seed_series(db, tmp_path, series=1, issues_per_series=5)
    big_root = tmp_path / "big"
    big_root.mkdir()
    big_ids, _ = await _seed_big(db, big_root)

    async def _measured(series_id: int) -> tuple[list[str], repo.SeriesStatistics]:
        statements: list[str] = []

        def capture(_conn, _cursor, statement, *_args) -> None:
            if "select" in statement.casefold():
                statements.append(statement)

        event.listen(db.engine.sync_engine, "before_cursor_execute", capture)
        try:
            async with db.read_session() as session:
                stats = await repo.series_statistics(session, series_id)
        finally:
            event.remove(db.engine.sync_engine, "before_cursor_execute", capture)
        return statements, stats

    small_stmts, small_stats = await _measured(small_ids[0])
    big_stmts, big_stats = await _measured(big_ids[0])

    # Correct aggregates at both scales (files on every second issue).
    assert small_stats.issue_count == 5
    assert big_stats.issue_count == 40
    assert big_stats.file_count == 20
    assert big_stats.missing_count == 20
    assert big_stats.size_on_disk == 20 * 25_000_000

    # Constant statement count, independent of row count...
    assert len(small_stmts) == len(big_stmts), (
        f"statistics statement count grew with row count: "
        f"{len(small_stmts)} -> {len(big_stmts)}"
    )
    assert len(big_stmts) <= 6, big_stmts
    # ...and every statement is an aggregation, not a row fetch.
    aggregates = ("count(", "sum(", "max(", "min(")
    for statement in big_stmts:
        lowered = statement.casefold()
        assert any(fn in lowered for fn in aggregates), (
            f"non-aggregate statement in series_statistics: {statement}"
        )


async def _seed_big(db, root: Path) -> tuple[list[int], int]:
    """One series with 40 issues (files on every second one) under ``root``."""
    profile_id = await _format_profile_id(db)
    now = utcnow()
    async with db.write_session() as session:
        rf = await repo.create_root_folder(session, str(root))
        row = await repo.create_series(
            session,
            cv_volume_id=999_999,
            title="Big Series",
            start_year=2020,
            format_profile_id=profile_id,
            root_folder_id=rf.id,
            path=str(root / "Big Series"),
            monitored=True,
        )
        issues = [
            IssueRow(
                series_id=row.id,
                cv_issue_id=2_000_000 + n,
                issue_number=str(n),
                ordering_key=ordering_key_for(str(n)),
                cover_date=dt.date(2021, (n % 12) + 1, 1),
                monitored=True,
                added_at=now,
            )
            for n in range(1, 41)
        ]
        session.add_all(issues)
        await session.flush()
        session.add_all(
            IssueFileRow(
                issue_id=issue.id,
                path=str(root / f"big-{issue.cv_issue_id}.cbz"),
                size=25_000_000,
                added_at=now,
            )
            for i, issue in enumerate(issues)
            if i % 2 == 0
        )
        return [row.id], rf.id


# --- opt-in latency benchmark (FORAGERR_NFR_PERF=1) -------------------------------


@perf_gate
@pytest.mark.req("FRG-NFR-003")
async def test_ui_read_endpoints_p95_latency_within_budget(tmp_path):
    """Load benchmark against a seeded 5,000-issue library: the five UI read
    endpoints (series list, series detail, queue, history, wanted) each answer
    with p95 latency under 500 ms."""
    warmups, samples = 3, 20
    async with running_app(_settings(tmp_path)) as (app, client):
        db = app.state.db
        series_ids, _ = await _seed_series(
            db,
            tmp_path,
            series=SEEDED_SERIES,
            issues_per_series=SEEDED_ISSUES // SEEDED_SERIES,
        )
        now = utcnow()
        async with db.write_session() as session:
            session.add_all(
                ImportHistoryRow(
                    event_type=EVENT_IMPORTED if i % 2 else EVENT_GRABBED,
                    series_id=series_ids[i % len(series_ids)],
                    source_title=f"Perf Series {i % 100:03d} #{i % 25 + 1}",
                    created_at=now - dt.timedelta(minutes=i),
                )
                for i in range(500)
            )
            session.add_all(
                TrackedDownloadRow(
                    download_id=f"perf-nzb-{i}",
                    client_name="sabnzbd",
                    state="downloading",
                    status="ok",
                    series_id=series_ids[i % len(series_ids)],
                    title=f"Perf.Series.{i:03d}",
                    total_size=250_000_000,
                    remaining_size=100_000_000,
                    added_at=now - dt.timedelta(minutes=i),
                    updated_at=now,
                )
                for i in range(50)
            )

        endpoints = {
            "series-list": ("/api/v1/series", {"pageSize": 20}),
            "series-detail": (f"/api/v1/series/{series_ids[0]}", {}),
            "queue": ("/api/v1/queue", {"pageSize": 20}),
            "history": ("/api/v1/history", {"pageSize": 20}),
            "wanted": ("/api/v1/wanted/missing", {"pageSize": 20}),
        }

        results: dict[str, float] = {}
        for name, (path, params) in endpoints.items():
            latencies: list[float] = []
            for i in range(warmups + samples):
                t0 = time.perf_counter()
                response = await client.get(path, params=params)
                elapsed = time.perf_counter() - t0
                assert response.status_code == 200, f"{name}: {response.status_code}"
                if i >= warmups:
                    latencies.append(elapsed)
            results[name] = _p95(latencies)

    over_budget = {
        name: p95 for name, p95 in results.items() if p95 >= P95_BUDGET_SECONDS
    }
    readable = {name: f"{p95 * 1000:.1f}ms" for name, p95 in results.items()}
    assert not over_budget, (
        f"endpoints over the {P95_BUDGET_SECONDS * 1000:.0f}ms p95 budget: "
        f"{readable}"
    )
    print(
        f"\nNFR-003 benchmark ({SEEDED_ISSUES} issues / {SEEDED_SERIES} series, "
        f"{samples} samples per endpoint): p95 {readable} "
        f"(budget {P95_BUDGET_SECONDS * 1000:.0f}ms)"
    )
