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
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from foragerr.app import create_app
from foragerr.indexers import IndexerSearchOutcome
from foragerr.config import (
    SEARCH_BUDGET_CEILING,
    SEARCH_BUDGET_FLOOR,
    SEARCH_BUDGET_LISTENER_MARGIN,
)
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

    # The absolute ceiling only bites once the listener guard is wide enough to
    # allow it — otherwise the guard is the tighter bound (see below).
    assert effective_search_budget(
        make_settings(
            tmp_path,
            indexer_search_time_budget_seconds=600.0,
            listener_request_timeout_seconds=300,
        )
    ) == SEARCH_BUDGET_CEILING
    # The default must leave the listener's request guard room to spare.
    default = make_settings(tmp_path)
    assert effective_search_budget(default) < default.listener_request_timeout_seconds


@pytest.mark.req("FRG-SRCH-015")
def test_budget_is_clamped_under_the_listener_request_guard(tmp_path: Path, caplog):
    """The gap the absolute ceiling left open: it is 60 s while the default
    listener guard is 30 s, so a configured 31..60 passed the clamp untouched
    and quietly reinstated the very 503 the budget exists to prevent. The
    effective ceiling is the CONFIGURED guard less the margin."""
    with caplog.at_level("WARNING"):
        clamped = effective_search_budget(
            make_settings(
                tmp_path,
                indexer_search_time_budget_seconds=45.0,
                listener_request_timeout_seconds=30,
            )
        )
    # 30 s guard - 5 s margin: inside the ceiling, and warned about.
    assert clamped == 30 - SEARCH_BUDGET_LISTENER_MARGIN == 25.0
    assert "indexer_search_time_budget_seconds" in caplog.text
    assert "listener_request_timeout_seconds" in caplog.text

    # It tracks the guard DOWN as well as up — a tightened guard tightens the
    # budget with it, with no second setting to remember.
    assert effective_search_budget(
        make_settings(
            tmp_path,
            indexer_search_time_budget_seconds=20.0,
            listener_request_timeout_seconds=15,
        )
    ) == 10.0

    # ...but never below the floor: a pathological 1 s guard would otherwise
    # compute a negative budget and cancel every indexer before its first page.
    assert effective_search_budget(
        make_settings(
            tmp_path,
            indexer_search_time_budget_seconds=20.0,
            listener_request_timeout_seconds=1,
        )
    ) == SEARCH_BUDGET_FLOOR

    # The invariant, stated once: whatever is configured, the enforced budget
    # always leaves the listener's guard room to answer.
    for budget, guard in ((45.0, 30), (60.0, 20), (5.0, 300), (600.0, 45)):
        settings = make_settings(
            tmp_path,
            indexer_search_time_budget_seconds=budget,
            listener_request_timeout_seconds=guard,
        )
        assert effective_search_budget(settings) <= max(
            SEARCH_BUDGET_FLOOR, guard - SEARCH_BUDGET_LISTENER_MARGIN
        )


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


# --- fan-out hygiene: cancellation, isolation, stragglers -------------------
#
# The budget makes the pipeline cancel live work on a human's clock, and every
# one of these tests is about the debris that leaves behind. They drive
# ``_budgeted_fan``/``_search_one_indexer`` directly with synthetic searches:
# the interleavings under test (an outer cancel landing mid-fan, a child that
# blows up while unwinding, a task that finishes microseconds late) cannot be
# provoked reliably through a socket.


@pytest.fixture
def _clean_stragglers():
    """Isolate the module-global straggler set around a test."""
    pipeline._STRAGGLERS.clear()
    yield pipeline._STRAGGLERS
    for task in list(pipeline._STRAGGLERS):
        task.cancel()
    pipeline._STRAGGLERS.clear()


def _row(indexer_id: int, name: str):
    """The two attributes ``_budgeted_fan`` reads off an indexer row."""
    return SimpleNamespace(id=indexer_id, name=name)


def _outcome_for(row) -> IndexerSearchOutcome:
    return IndexerSearchOutcome(indexer_id=row.id, indexer_name=row.name)


@pytest.mark.req("FRG-SRCH-015")
async def test_outer_cancellation_parks_the_children_it_takes_down(
    _clean_stragglers,
):
    """Shutdown (or a client hang-up) cancels the whole fan. The children were
    cancelled but NOT held, so the last reference to a still-unwinding task died
    with the frame — the "Task was destroyed but it is pending!" noise at
    shutdown. They are parked now, exactly as the budget path parks its own."""
    unwinding = asyncio.Event()

    async def slow(row):
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            unwinding.set()
            await asyncio.sleep(0.05)  # a real unwind is not instantaneous
            raise

    rows = [_row(1, "A"), _row(2, "B")]
    outer = asyncio.create_task(pipeline._budgeted_fan(rows, slow, 30.0))
    await asyncio.sleep(0.05)  # let both children reach their await

    outer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await outer

    await unwinding.wait()
    # Held through the unwind: the loop can never collect a pending task.
    assert len(pipeline._STRAGGLERS) == 2
    assert all(t.cancelled() or not t.done() for t in pipeline._STRAGGLERS)

    # ...and each drops itself the moment it has actually finished.
    await asyncio.sleep(0.15)
    assert not pipeline._STRAGGLERS


@pytest.mark.req("FRG-SRCH-015")
async def test_a_cancelled_indexer_never_penalises_the_backoff_ladder(
    db, monkeypatch
):
    """A timeout must never look like a failure (that is the whole design).
    ``CancelledError`` passes through the isolation untouched, so an ORDINARY
    exception raised while the cancelled task unwinds (a client's cleanup
    tripping over a half-closed socket) — which lands in the same handler and
    looks exactly like a crash — must not escalate a merely SLOW indexer on
    the ladder."""

    async def unwinds_badly(*args, **kwargs):
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            raise RuntimeError("cleanup blew up on a half-closed socket") from None

    monkeypatch.setattr(pipeline, "search_indexer", unwinds_badly)
    backoff = ProviderBackoff(db)
    row = _row(4242, "Slow")

    task = asyncio.create_task(
        pipeline._search_one_indexer(
            row,
            None,
            factory=None,
            backoff=backoff,
            caps_cache=None,
            retention_days=None,
            min_interval=0.0,
        )
    )
    await asyncio.sleep(0.05)
    task.cancel()
    outcome = await task

    # Still isolated to one provider (the fan is unharmed)...
    assert outcome.indexer_id == row.id
    assert outcome.failure is not None
    # ...but the ladder is untouched: a slow indexer is not a failing one.
    status = await backoff.status(PROVIDER_INDEXER, row.id)
    assert status.failure_count == 0
    assert status.active is False


@pytest.mark.req("FRG-NFR-010")
async def test_an_unmapped_task_error_isolates_instead_of_aborting_the_fan(
    _clean_stragglers,
):
    """``task.result()`` re-raised whatever the in-task isolation could not map
    — and that abandoned the WHOLE fan, throwing away every other indexer's real
    results over one provider's mess. It becomes that provider's failed outcome
    now, and everyone else still reports."""

    class _Unmappable(BaseException):
        """Not caught by the in-task ``except Exception`` isolation."""

    async def one_bad_apple(row):
        if row.name == "Bad":
            raise _Unmappable("something the isolation cannot see")
        return _outcome_for(row)

    rows = [_row(1, "Bad"), _row(2, "Good")]
    outcomes = await pipeline._budgeted_fan(rows, one_bad_apple, 5.0)

    assert [o.indexer_name for o in outcomes] == ["Bad", "Good"]
    bad, good = outcomes
    assert bad.failure is not None
    assert "_Unmappable" in str(bad.failure)
    assert bad.timed_out is False  # a crash is not a timeout
    assert good.failure is None  # the healthy indexer still reported


@pytest.mark.req("FRG-SRCH-015")
async def test_a_task_that_finished_at_the_deadline_keeps_its_results(
    _clean_stragglers, monkeypatch
):
    """DELIBERATE: a task that completes in the sliver between ``asyncio.wait``
    returning and its cancel being delivered is done-but-not-cancelled, so its
    FULL results are kept and it is reported as searched — despite technically
    missing the deadline by microseconds. Real results in hand beat discarding
    them over a stopwatch; the wait the budget exists to bound has already
    happened.

    The stub reproduces exactly that interleaving: ``wait`` reports a task as
    pending which has, by the time the caller resumes, already finished."""
    real_wait = asyncio.wait

    async def wait_reporting_a_late_finisher(tasks, *, timeout=None, **kwargs):
        await asyncio.sleep(0)  # let the (fast) searches complete...
        await asyncio.sleep(0)
        if any(not t.done() for t in tasks):  # the grace wait: behave normally
            return await real_wait(tasks, timeout=timeout, **kwargs)
        return set(), set(tasks)  # ...then report them as still pending

    monkeypatch.setattr(pipeline.asyncio, "wait", wait_reporting_a_late_finisher)

    async def finishes_just_late(row):
        outcome = _outcome_for(row)
        outcome.skipped_items = 7  # a marker for "its real results survived"
        return outcome

    rows = [_row(1, "JustLate")]
    outcomes = await pipeline._budgeted_fan(rows, finishes_just_late, 0.01)

    assert len(outcomes) == 1
    assert outcomes[0].timed_out is False  # reported as searched, not timed out
    assert outcomes[0].skipped_items == 7  # ...with its work intact
    assert not pipeline._STRAGGLERS  # nothing parked: it had already finished


@pytest.mark.req("FRG-SRCH-015")
async def test_a_straggler_that_survived_its_cancel_is_chased_by_the_next_fan(
    _clean_stragglers,
):
    """The residual the grace period cannot close: a task that swallows its
    first cancel would otherwise sit parked until the process exits. Every fan
    re-issues the cancel on entry, so a straggler is bounded by the NEXT
    interactive search rather than accumulating — and nothing is awaited, so
    chasing it cannot delay the operator."""
    cancels = 0

    async def stubborn(row):
        nonlocal cancels
        while True:
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                cancels += 1
                if cancels > 1:
                    raise  # gives up on the second ask
                # ...swallows the first and carries on, which is the whole bug

    await pipeline._budgeted_fan([_row(1, "Stubborn")], stubborn, 0.05)
    assert cancels == 1
    assert len(pipeline._STRAGGLERS) == 1  # survived, parked, still running

    # A later interactive search: unrelated indexer, and the straggler is chased.
    async def quick(row):
        return _outcome_for(row)

    await pipeline._budgeted_fan([_row(2, "Other")], quick, 5.0)
    await asyncio.sleep(0.05)

    assert cancels == 2
    assert not pipeline._STRAGGLERS
