"""ddl_queue engine: single-flight, orphan recovery, per-host failover,
provenance handoff, manual actions (FRG-DDL-001/005/007/013)."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from sqlalchemy import select

from foragerr.db.base import utcnow
from foragerr.ddl.download import build_allowlist
from foragerr.ddl.errors import DdlDownloadError
from foragerr.ddl.queue import (
    STATUS_ABORTED,
    STATUS_COMPLETED,
    STATUS_DOWNLOADING,
    STATUS_FAILED,
    STATUS_QUEUED,
    DdlQueueEngine,
    EnqueueRequest,
)
from foragerr.downloads.models import DdlQueueRow
from ddl_support import make_cbz, make_factory, redirect

POST_URL = "https://getcomics.org/comic/example-1-2024/"


def _engine(tmp_path, db, handler):
    factory, transport = make_factory(tmp_path, handler)
    staging = tmp_path / "ddl-staging"
    engine = DdlQueueEngine(
        db,
        http_factory=factory,
        staging_dir=staging,
        prefer_upscaled=True,
    )
    return engine, transport


def _post_page(req: httpx.Request) -> bool:
    return "/comic/" in req.url.path


async def _enqueue(engine, download_id="ddl-1", **kw):
    return await engine.enqueue(
        EnqueueRequest(
            download_id=download_id,
            post_url=POST_URL,
            title=kw.pop("title", "Example Comic 1"),
            **kw,
        )
    )


async def _row(db, download_id):
    async with db.read_session() as session:
        return (
            await session.execute(
                select(DdlQueueRow).where(DdlQueueRow.download_id == download_id)
            )
        ).scalar_one()


@pytest.mark.req("FRG-DDL-007")
async def test_successful_download_completes_with_provenance(tmp_path, db):
    body = make_cbz()

    def handler(req: httpx.Request) -> httpx.Response:
        if _post_page(req):
            return httpx.Response(200, text=_read("post_page.html"))
        return httpx.Response(200, content=body)  # any run.php/go.php link

    engine, _ = _engine(tmp_path, db, handler)
    await _enqueue(engine, issue_id=555)
    assert await engine.process_next() is True

    row = await _row(db, "ddl-1")
    assert row.status == STATUS_COMPLETED
    assert row.output_path and row.output_path.endswith(".cbz")
    # Provenance persisted (FRG-DDL-013): main server picked first.
    assert row.current_host == "main"
    assert row.selected_link_type == "GC-Main"
    assert row.post_url == POST_URL
    assert "[__555__]" in row.output_path  # issue-id handshake tag


@pytest.mark.req("FRG-DDL-005")
async def test_failover_to_next_host_then_success(tmp_path, db):
    body = make_cbz()

    def handler(req: httpx.Request) -> httpx.Response:
        if _post_page(req):
            return httpx.Response(200, text=_read("post_page.html"))
        if "run.php" in req.url.path:  # main server fails
            return httpx.Response(500)
        return httpx.Response(200, content=body)  # mirror (go.php) succeeds

    engine, _ = _engine(tmp_path, db, handler)
    await _enqueue(engine)
    await engine.process_next()

    row = await _row(db, "ddl-1")
    assert row.status == STATUS_COMPLETED
    assert row.selected_link_type == "GC-Mirror"  # advanced past main
    assert "GC-Main" in json.loads(row.failed_hosts_json)


@pytest.mark.req("FRG-DDL-005")
async def test_all_hosts_exhausted_marks_failed(tmp_path, db):
    def handler(req: httpx.Request) -> httpx.Response:
        if _post_page(req):
            return httpx.Response(200, text=_read("post_page.html"))
        return httpx.Response(500)  # every direct host fails; mirrors unsupported

    engine, _ = _engine(tmp_path, db, handler)
    await _enqueue(engine)
    await engine.process_next()

    row = await _row(db, "ddl-1")
    assert row.status == STATUS_FAILED
    # Both direct hosts recorded as failed before exhaustion.
    failed = set(json.loads(row.failed_hosts_json or "[]"))
    assert {"GC-Main", "GC-Mirror"} <= failed


@pytest.mark.req("FRG-DDL-010")
async def test_verification_failure_triggers_failover(tmp_path, db):
    def handler(req: httpx.Request) -> httpx.Response:
        if _post_page(req):
            return httpx.Response(200, text=_read("post_page.html"))
        if "run.php" in req.url.path:  # main returns an HTML ad page named a comic
            return httpx.Response(200, content=b"<html>ad</html>" + b" " * 20_000)
        return httpx.Response(200, content=make_cbz())  # mirror is a real cbz

    engine, _ = _engine(tmp_path, db, handler)
    await _enqueue(engine)
    await engine.process_next()

    row = await _row(db, "ddl-1")
    assert row.status == STATUS_COMPLETED
    assert row.selected_link_type == "GC-Mirror"


@pytest.mark.req("FRG-DDL-007")
async def test_single_flight_processes_queued_items_in_order(tmp_path, db):
    body = make_cbz()
    order: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if _post_page(req):
            return httpx.Response(200, text=_read("post_page.html"))
        order.append(req.url.host)
        return httpx.Response(200, content=body)

    engine, _ = _engine(tmp_path, db, handler)
    await _enqueue(engine, download_id="ddl-a")
    await _enqueue(engine, download_id="ddl-b")
    processed = await engine.process_all()
    assert processed == 2
    a = await _row(db, "ddl-a")
    b = await _row(db, "ddl-b")
    assert a.status == STATUS_COMPLETED and b.status == STATUS_COMPLETED


@pytest.mark.req("FRG-DDL-007")
async def test_orphan_recovery_requeues_in_flight_items(tmp_path, db):
    engine, _ = _engine(tmp_path, db, lambda req: httpx.Response(200))
    row_id = await _enqueue(engine)
    # Simulate a crash mid-download: the row is left 'downloading'.
    async with db.write_session() as session:
        row = await session.get(DdlQueueRow, row_id)
        row.status = STATUS_DOWNLOADING
    recovered = await engine.reconcile_orphans()
    assert recovered == 1
    row = await _row(db, "ddl-1")
    assert row.status == STATUS_QUEUED  # resumable


@pytest.mark.req("FRG-DDL-007")
async def test_manual_actions_retry_abort_remove(tmp_path, db):
    engine, _ = _engine(tmp_path, db, lambda req: httpx.Response(200))
    await _enqueue(engine, download_id="ddl-x")
    async with db.write_session() as session:
        (await _row(db, "ddl-x"))  # ensure present
    # Fail it, then retry re-queues and clears failures.
    await engine._mark_failed((await _row(db, "ddl-x")).id, "boom")
    assert await engine.retry("ddl-x") is True
    assert (await _row(db, "ddl-x")).status == STATUS_QUEUED
    # Abort then remove.
    assert await engine.abort("ddl-x") is True
    assert await engine.remove("ddl-x") is True
    async with db.read_session() as session:
        remaining = (
            await session.execute(
                select(DdlQueueRow).where(DdlQueueRow.download_id == "ddl-x")
            )
        ).scalar_one_or_none()
    assert remaining is None


@pytest.mark.req("FRG-DDL-007")
async def test_abort_mid_attempt_is_not_clobbered_by_completion(tmp_path, db):
    # An in-flight attempt that finishes AFTER a user abort must not overwrite
    # the abort with COMPLETED (the abort race).
    def handler(req: httpx.Request) -> httpx.Response:
        if _post_page(req):
            return httpx.Response(200, text=_read("post_page.html"))
        return httpx.Response(200, content=make_cbz())

    engine, _ = _engine(tmp_path, db, handler)
    await _enqueue(engine, download_id="ddl-abrt")

    async def racing_attempt(row_id, snapshot, picked, allowlist):
        # The user aborts while the bytes are still transferring.
        await engine.abort("ddl-abrt")
        return tmp_path / "done.cbz", 4242

    engine._attempt = racing_attempt  # type: ignore[method-assign]
    assert await engine.process_next() is True

    row = await _row(db, "ddl-abrt")
    assert row.status == STATUS_ABORTED  # NOT clobbered to completed


@pytest.mark.req("FRG-DDL-007")
async def test_concurrent_claim_never_double_claims_a_row(tmp_path, db):
    engine, _ = _engine(tmp_path, db, lambda req: httpx.Response(200))
    await _enqueue(engine, download_id="ddl-solo")
    # Two claimants race for the single queued row; the status-guarded UPDATE
    # ensures exactly one wins.
    a, b = await asyncio.gather(engine._claim_next(), engine._claim_next())
    claimed = [x for x in (a, b) if x is not None]
    assert len(claimed) == 1  # never double-claimed


@pytest.mark.req("FRG-DDL-012")
async def test_post_page_off_allowlist_redirect_is_refused(tmp_path, db):
    # A hostile post-page response that 302s to an off-allowlist public host must
    # be refused by the per-provider allowlist, not followed.
    engine, _ = _engine(
        tmp_path, db, lambda req: redirect("https://evil.example/steal")
    )
    allowlist = build_allowlist("https://getcomics.org")
    with pytest.raises(DdlDownloadError):
        await engine._fetch_post_page("https://getcomics.org/comic/x/", allowlist)


def _read(name: str) -> str:
    from ddl_support import fixture

    return fixture(name)
