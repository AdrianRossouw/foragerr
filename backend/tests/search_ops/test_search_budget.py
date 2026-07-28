"""The interactive per-indexer time budget (FRG-SRCH-015 / FRG-SRCH-014 /
FRG-API-008).

The rig finding this covers: one slow indexer held a whole interactive search
until the listener's 30 s request guard killed it (76 s+ observed). The budget
bounds each indexer's share of an INTERACTIVE search: at the deadline the
indexers that finished contribute their complete decisions, the stragglers are
cancelled and reported as timed-out outcomes, and the operator gets a partial —
visibly partial — result instead of a 503.

Two levels are exercised deliberately:

* the pipeline tests drive REAL sockets (``fixture_server``) so cancellation
  lands inside httpx's read on a live connection, not in a stub;
* the API tests drive the wired app over a paced stub transport, which is where
  the response shape and the cache/grab of a PARTIAL decision set are pinned.

``SEARCH_BUDGET_FLOOR`` is monkeypatched down in the timing tests: the shipped
5 s floor is right for an operator and wrong for a test suite. The floor itself
is pinned by the clamp test, against the real constants.
"""

from __future__ import annotations

import asyncio
import time
from functools import partial
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from foragerr.app import create_app
from foragerr.config import SEARCH_BUDGET_CEILING, SEARCH_BUDGET_FLOOR
from foragerr.http import HttpClientFactory
from foragerr.indexers import ratelimit
from foragerr.indexers.caps import CapsCache
from foragerr.providers.backoff import PROVIDER_INDEXER, ProviderBackoff
from foragerr.search_ops import pipeline
from foragerr.search_ops.pipeline import (
    effective_search_budget,
    run_search,
    search_budget_for_path,
)
from http_support import PUBLIC_V4, StubResolver, fixture_server, make_settings
from indexers_support import caps_doc, feed_item, newznab_feed

from .support import make_indexer, make_issue, make_series

#: Budgets short enough for a test to wait out, with the shipped floor lifted.
#: The pipeline tests run over real sockets under the 0.1 s politeness floor, so
#: the fast indexer needs a little room; the API tests neutralize the gate.
PIPELINE_BUDGET = 1.0
API_BUDGET = 0.5
#: How long a "slow indexer" sits on each SEARCH response — comfortably past the
#: budget, so a search that waited for it is unmistakable in the elapsed time.
SLOW_DELAY = 2.5


# --- real-socket fixtures ---------------------------------------------------


def _http(body: bytes) -> bytes:
    return (
        b"HTTP/1.1 200 OK\r\nContent-Length: "
        + str(len(body)).encode()
        + b"\r\nConnection: close\r\n\r\n"
        + body
    )


def _newznab_handler(*, guid: str, search_delay: float = 0.0):
    """A minimal live Newznab server: caps immediately, one item on the first
    page, an empty second page (so paging terminates), and ``search_delay``
    seconds of thinking time before every SEARCH response (caps stays fast, so
    a cancellation lands mid-paging exactly as it does on a real slow indexer).
    """

    async def handler(reader, writer):
        raw = await reader.readuntil(b"\r\n\r\n")
        path = raw.split(b" ", 2)[1].decode()
        if "t=caps" in path:
            writer.write(_http(caps_doc()))
            await writer.drain()
            return
        if search_delay:
            await asyncio.sleep(search_delay)
        if "offset=0" in path:
            body = newznab_feed(feed_item(guid=guid, title="Saga 007 (2012)"))
        else:
            body = newznab_feed()
        writer.write(_http(body))
        await writer.drain()

    return handler


def _live_factory(tmp_path: Path) -> HttpClientFactory:
    return HttpClientFactory(
        make_settings(tmp_path), test_allow_addresses={"127.0.0.1"}
    )


async def _search_fast_and_slow(
    db, tmp_path, *, path: str, series_id, issue_id, budget: float, slow_delay: float
):
    """Search a slow + a fast indexer on ``path``; return (result, slow_id)."""
    async with fixture_server(
        _newznab_handler(guid="slow-1", search_delay=slow_delay)
    ) as slow_base, fixture_server(_newznab_handler(guid="fast-1")) as fast_base:
        # Slow FIRST: outcome order follows the row order, never completion.
        slow_id = await make_indexer(db, name="Slow", base_url=slow_base, priority=5)
        await make_indexer(db, name="Fast", base_url=fast_base, priority=10)
        result = await run_search(
            db=db,
            settings=make_settings(
                tmp_path, indexer_search_time_budget_seconds=budget
            ),
            factory=_live_factory(tmp_path),
            backoff=ProviderBackoff(db),
            caps_cache=CapsCache(),
            series_id=series_id,
            issue_id=issue_id,
            path=path,
            min_interval=0.0,  # the 2 s politeness gate is not under test here
        )
        return result, slow_id


@pytest.fixture
def _tiny_budget_floor(monkeypatch):
    """Lift the shipped 5 s clamp floor so a test can use a sub-second budget."""
    monkeypatch.setattr(pipeline, "SEARCH_BUDGET_FLOOR", 0.05)


# --- the budget itself ------------------------------------------------------


@pytest.mark.req("FRG-SRCH-015")
async def test_slow_indexer_is_cancelled_and_the_fast_one_still_decides(
    db, format_profile_id, root_folder_id, _tiny_budget_floor
):
    """The slowest indexer no longer holds the search: the fast indexer's
    decisions come back inside the budget envelope and the slow one is reported
    as timed out — never a whole-request failure."""
    series_id = await make_series(
        db, format_profile_id=format_profile_id, root_folder_id=root_folder_id
    )
    issue_id = await make_issue(db, series_id=series_id, issue_number="7")

    started = time.monotonic()
    result, slow_id = await _search_fast_and_slow(
        db, db.db_path.parent, path="interactive",
        series_id=series_id, issue_id=issue_id,
        budget=PIPELINE_BUDGET, slow_delay=SLOW_DELAY,
    )
    elapsed = time.monotonic() - started

    assert result is not None
    # Bounded by the budget, NOT by the slow indexer's thinking time.
    assert elapsed < SLOW_DELAY, f"search waited for the slow indexer ({elapsed}s)"
    # The fast indexer's decisions are complete and grabbable.
    assert result.approved
    assert result.approved[0].candidate.indexer_name == "Fast"

    slow = next(o for o in result.indexer_outcomes if o.indexer_name == "Slow")
    assert slow.timed_out is True
    assert slow.time_budget_seconds == PIPELINE_BUDGET
    assert slow.candidates == []  # no half-read page is silently mixed in
    assert slow.failure is None  # a timeout is an outcome, not an error
    fast = next(o for o in result.indexer_outcomes if o.indexer_name == "Fast")
    assert fast.timed_out is False
    assert fast.candidates

    # ...and the cancellation left the slow indexer's ladder untouched: a slow
    # indexer is not a failing one, so nothing was recorded against it.
    status = await ProviderBackoff(db).status(PROVIDER_INDEXER, slow_id)
    assert status.failure_count == 0
    assert status.level == 0
    assert status.active is False

    # The cancellation also unwound cleanly through the process-global
    # politeness gate it was spacing requests with: no lock is left held, so
    # the next search of that indexer is not deadlocked behind a dead task.
    gate = ratelimit._GATES.get(slow_id)
    assert gate is not None and not gate._lock.locked()


@pytest.mark.req("FRG-SRCH-015")
async def test_scheduled_path_is_never_budgeted(
    db, format_profile_id, root_folder_id, _tiny_budget_floor
):
    """Backlog/automatic searches stay politeness-first: an indexer slower than
    the configured budget (which would be cancelled on the interactive path)
    runs to completion here."""
    series_id = await make_series(
        db, format_profile_id=format_profile_id, root_folder_id=root_folder_id
    )
    issue_id = await make_issue(db, series_id=series_id, issue_number="7")

    result, _ = await _search_fast_and_slow(
        db, db.db_path.parent, path="auto",
        series_id=series_id, issue_id=issue_id,
        # Every one of its responses is well past the budget; unbudgeted means
        # unbudgeted, so it still finishes (kept short — the test WAITS for it).
        budget=0.2, slow_delay=0.6,
    )

    assert result is not None
    assert not any(o.timed_out for o in result.indexer_outcomes)
    slow = next(o for o in result.indexer_outcomes if o.indexer_name == "Slow")
    assert slow.candidates  # it waited politely and got its results


@pytest.mark.req("FRG-SRCH-015")
def test_budget_applies_to_the_interactive_path_only(tmp_path: Path):
    """The path gate is structural — the scheduled paths cannot be budgeted by
    any configuration value."""
    settings = make_settings(tmp_path, indexer_search_time_budget_seconds=12.0)
    assert search_budget_for_path(settings, "interactive") == 12.0
    assert search_budget_for_path(settings, "auto") is None
    assert search_budget_for_path(settings, "rss") is None
    # No settings at all (the pipeline's optional-settings callers) = no budget.
    assert search_budget_for_path(None, "interactive") is None


@pytest.mark.req("FRG-SRCH-015")
def test_budget_is_clamped_to_the_documented_range(tmp_path: Path, caplog):
    """An out-of-range budget warns and is corrected, never fails startup."""
    assert effective_search_budget(
        make_settings(tmp_path, indexer_search_time_budget_seconds=20.0)
    ) == 20.0

    with caplog.at_level("WARNING"):
        too_low = effective_search_budget(
            make_settings(tmp_path, indexer_search_time_budget_seconds=0.5)
        )
    assert too_low == SEARCH_BUDGET_FLOOR
    assert "indexer_search_time_budget_seconds" in caplog.text

    assert effective_search_budget(
        make_settings(tmp_path, indexer_search_time_budget_seconds=600.0)
    ) == SEARCH_BUDGET_CEILING
    # The default must leave the listener's request guard room to spare.
    default = make_settings(tmp_path)
    assert effective_search_budget(default) < default.listener_request_timeout_seconds


@pytest.mark.req("FRG-SRCH-015")
async def test_cancelling_a_politeness_wait_leaves_the_gate_clean():
    """The gate is where a cancelled indexer is most likely to be waiting, so
    its state must survive: the lock is released, and the spacing stays measured
    from the request that really went out (a cancelled acquire never stamps a
    fresh timestamp, which would let the NEXT request out too early)."""
    ratelimit.reset_gates()
    try:
        await ratelimit.acquire(1, 10.0)  # first call passes straight through
        gate = ratelimit._gate_for(1)
        stamped = gate._last

        waiter = asyncio.create_task(ratelimit.acquire(1, 10.0))
        await asyncio.sleep(0.05)  # let it reach the politeness sleep
        assert gate._lock.locked()
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter

        assert not gate._lock.locked()  # the lock came back
        assert gate._last == stamped  # spacing still measured from the real request
        # A following acquire therefore still WAITS — the gate did not forget.
        follow = asyncio.create_task(ratelimit.acquire(1, 10.0))
        await asyncio.sleep(0.05)
        assert not follow.done()
        follow.cancel()
        with pytest.raises(asyncio.CancelledError):
            await follow
    finally:
        ratelimit.reset_gates()


# --- the wire shape, over the wired app -------------------------------------

FAST_HOST = "fast-indexer.test"
SLOW_HOST = "slow-indexer.test"


def _stub_feed(request: httpx.Request) -> httpx.Response:
    params = request.url.params
    if params.get("t") == "caps":
        return httpx.Response(200, content=caps_doc())
    if int(params.get("offset", "0")) > 0:
        return httpx.Response(200, content=newznab_feed())
    return httpx.Response(
        200,
        content=newznab_feed(
            feed_item(guid=f"{request.url.host}-1", title="Saga 007 (2012)")
        ),
    )


class _PacedTransport(httpx.AsyncBaseTransport):
    """Serves the stub feed, delaying SEARCH responses per host — a slow indexer
    without the cost of a real socket."""

    def __init__(self, delays: dict[str, float]) -> None:
        self._delays = delays

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        delay = self._delays.get(request.url.host or "", 0.0)
        if delay and request.url.params.get("t") != "caps":
            await asyncio.sleep(delay)
        return _stub_feed(request)


@pytest.fixture
def _no_rate_gate(monkeypatch):
    """Neutralize the per-indexer 2 s spacing gate for the API tests (the
    release path uses the production interval and these are stubbed).

    Deliberately NOT autouse: the gate's own cancellation behavior is under test
    in this module, and a module-wide patch would quietly hollow that out."""

    async def _immediate(indexer_id: int, min_interval: float = 0.0) -> None:
        return

    monkeypatch.setattr("foragerr.indexers.ratelimit.acquire", _immediate)


@pytest.fixture
def api_client(tmp_path: Path, _tiny_budget_floor, _no_rate_gate):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    settings = make_settings(cfg, indexer_search_time_budget_seconds=API_BUDGET)
    app = create_app(settings)
    app.state.http_factory = HttpClientFactory(
        settings,
        resolver=StubResolver({FAST_HOST: [PUBLIC_V4], SLOW_HOST: [PUBLIC_V4]}),
        transport=_PacedTransport({SLOW_HOST: SLOW_DELAY}),
    )
    with TestClient(app) as c:
        yield c


async def _seed(db, *, with_slow: bool) -> tuple[int, int, int]:
    from foragerr.library import repo

    from .support import profile_id

    pid = await profile_id(db)
    root = db.db_path.parent / "root"
    root.mkdir(exist_ok=True)
    async with db.write_session() as session:
        rf = await repo.create_root_folder(session, str(root))
        root_folder_id = rf.id
    series_id = await make_series(
        db, format_profile_id=pid, root_folder_id=root_folder_id
    )
    issue_id = await make_issue(db, series_id=series_id, issue_number="7")
    fast_id = await make_indexer(
        db, name="Fast", base_url=f"https://{FAST_HOST}", priority=10
    )
    slow_id = 0
    if with_slow:
        slow_id = await make_indexer(
            db, name="Slow", base_url=f"https://{SLOW_HOST}", priority=5
        )
    return issue_id, fast_id, slow_id


@pytest.mark.req("FRG-API-008")
@pytest.mark.req("FRG-SRCH-014")
def test_partial_response_carries_outcomes_and_still_caches_and_grabs(api_client):
    """A partial decision set is machine-readably partial — and caches and grabs
    exactly as a full one does."""
    db = api_client.app.state.db
    issue_id, fast_id, slow_id = api_client.portal.call(
        partial(_seed, db, with_slow=True)
    )

    started = time.monotonic()
    resp = api_client.get("/api/v1/release", params={"issueId": issue_id})
    elapsed = time.monotonic() - started

    assert resp.status_code == 200  # never a whole-request 503
    assert elapsed < SLOW_DELAY
    body = resp.json()

    rows = body["releases"]
    assert rows and all(r["indexer_id"] == fast_id for r in rows)

    outcomes = {o["indexer_id"]: o for o in body["indexers"]}
    assert outcomes[fast_id]["outcome"] == "searched"
    assert outcomes[fast_id]["budget_seconds"] is None
    assert outcomes[slow_id]["outcome"] == "timed_out"
    assert outcomes[slow_id]["name"] == "Slow"
    assert outcomes[slow_id]["budget_seconds"] == API_BUDGET
    assert outcomes[slow_id]["candidate_count"] == 0

    # The partial set cached: grabbing a returned row works identically.
    approved = next(r for r in rows if r["approved"])
    grab = api_client.post(
        "/api/v1/release",
        json={"indexer_id": approved["indexer_id"], "guid": approved["guid"]},
    )
    assert grab.status_code == 201
    assert grab.json()["payload"]["guid"] == approved["guid"]


@pytest.mark.req("FRG-API-008")
def test_a_complete_search_reports_every_indexer_as_searched(api_client):
    """The quiet case: nothing slow, so the outcomes field says so plainly."""
    db = api_client.app.state.db
    issue_id, fast_id, _ = api_client.portal.call(partial(_seed, db, with_slow=False))

    body = api_client.get("/api/v1/release", params={"issueId": issue_id}).json()

    assert body["releases"]
    assert [o["outcome"] for o in body["indexers"]] == ["searched"]
    assert body["indexers"][0]["indexer_id"] == fast_id
    assert body["indexers"][0]["budget_seconds"] is None


@pytest.mark.req("FRG-API-008")
def test_backing_off_and_failed_indexers_keep_their_own_outcomes():
    """The outcome mapping never collapses the four states into each other —
    a timeout in particular is neither a failure nor a back-off."""
    from foragerr.api.release import _outcome_row
    from foragerr.indexers import IndexerSearchOutcome
    from foragerr.indexers.errors import IndexerUnavailable

    searched = _outcome_row(IndexerSearchOutcome(indexer_id=1, indexer_name="A"))
    assert searched.outcome == "searched"

    backing = _outcome_row(
        IndexerSearchOutcome(indexer_id=2, indexer_name="B", backing_off=True)
    )
    assert backing.outcome == "backing_off"

    failed = _outcome_row(
        IndexerSearchOutcome(
            indexer_id=3, indexer_name="C", failure=IndexerUnavailable("boom")
        )
    )
    assert failed.outcome == "failed"
    assert failed.budget_seconds is None

    timed_out = _outcome_row(
        IndexerSearchOutcome(
            indexer_id=4,
            indexer_name="D",
            timed_out=True,
            time_budget_seconds=20.0,
        )
    )
    assert timed_out.outcome == "timed_out"
    assert timed_out.budget_seconds == 20.0
