"""Process-global ComicVine rate limiter (FRG-META-003, FRG-NFR-004).

ONE asyncio token gate serializes every ComicVine request in the process —
search, volume, issue pagination AND the covers-cache fetch — so observed
inter-request wire times never fall below the configured minimum interval
(default 2 s). Mylar's blind per-call sleep and unlocked concurrency are the
anti-patterns this replaces: concurrent callers queue on the gate rather than
bursting. (Scope note, FRG-META-016/021: the *candidate-cover proxy* streams
media-CDN bytes for a review screen and is deliberately outside this API
budget — it is not a ComicVine API resource path. The covers CACHE fetch in
:mod:`foragerr.metadata.covers` IS budgeted, in its own ``covers`` bucket.)

Three dimensions ride this one gate, never a second gate:

* **velocity** (FRG-META-003) — the min-interval spacing above;
* **path budget** (FRG-META-016) — a rolling-hour admission ceiling per
  resource path bucket, refused locally with a typed error;
* **lane** (FRG-META-022) — every acquisition is ``batch`` (scheduled and
  background work) or ``interactive`` (an operator is waiting). Batch
  admissions are capped at a configurable share of each path budget (default
  70%) so an interactive reserve always exists; interactive admissions may
  consume the full path budget. An undeclared lane counts as ``batch``:
  fail-frugal, so a background caller added without lane awareness degrades
  itself rather than the operator's interactive surfaces.

On a rate-limit signal (HTTP 420/429 or a detected ban page) the gate is told
to back off for ``max(Retry-After, exponential backoff)`` and flips a degraded
flag; the next :meth:`acquire` blocks until the cool-down elapses, then clears
the flag automatically. The degraded state is exposed via :func:`comicvine_health`
for the API health endpoint to consume (wiring is the api agent's job).

The gate is module-global by design — rate limiting must hold no matter how
many client instances exist. :func:`reset_gate` exists only for test isolation.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections import deque

from foragerr.metadata.errors import ComicVineBudgetExhausted

logger = logging.getLogger("foragerr.metadata.ratelimit")

#: Absolute safety floor for the configured min-interval. An operator cannot
#: drive ComicVine faster than this regardless of configuration.
MIN_INTERVAL_FLOOR = 0.25

#: Exponential-backoff ceiling on repeated rate-limit signals.
MAX_BACKOFF_SECONDS = 300.0

#: The rolling window over which per-path admissions are counted (FRG-META-016).
#: ComicVine's server-side limit is per resource path per HOUR, so we count over
#: exactly one hour of monotonic time and prune anything older.
BUDGET_WINDOW_SECONDS = 3600.0

#: Documented bounds for the per-path hourly budget. The floor keeps the budget
#: usable; the ceiling never exceeds ComicVine's documented 200/hour/path limit.
BUDGET_FLOOR = 10
BUDGET_CEILING = 200

#: Fraction of the ceiling at which a bucket starts appearing in the health
#: payload (near-ceiling visibility before the deferral actually bites).
BUDGET_WARNING_FRACTION = 0.8

#: The two priority lanes (FRG-META-022). ``batch`` is the default for an
#: unclassified caller — an untagged newcomer can never eat the reserve.
LANE_BATCH = "batch"
LANE_INTERACTIVE = "interactive"

#: Documented bounds for the batch share of a path budget. The floor keeps
#: background work viable; the ceiling keeps a real interactive reserve.
BATCH_SHARE_FLOOR = 0.30
BATCH_SHARE_CEILING = 0.95

#: Last-resort batch share when the settings object cannot supply a usable
#: declared default (a stub/namespace in a test, a model without the field).
#: The real default is read off the Settings field itself, so the two cannot
#: drift for any real deployment.
BATCH_SHARE_FALLBACK = 0.70


def _declared_default(settings, name: str, fallback: float) -> float:
    """The DECLARED default for ``name`` on this settings object's own model.

    Read off ``type(settings).model_fields`` rather than duplicated here, so a
    non-finite configured value falls back to exactly the documented default an
    operator would read in the manual — and this module never becomes a second
    place the default is written down. Anything that cannot supply a usable
    number (a plain namespace in a test) yields ``fallback``.
    """
    field = getattr(type(settings), "model_fields", {}).get(name)
    default = getattr(field, "default", None)
    if isinstance(default, (int, float)) and math.isfinite(float(default)):
        return float(default)
    return fallback


def normalize_lane(lane: str | None) -> str:
    """Coerce a caller-supplied lane to one of the two known lanes.

    Anything that is not exactly :data:`LANE_INTERACTIVE` — ``None``, a typo, a
    lane a future version might add — is accounted as :data:`LANE_BATCH`. The
    frugal side is the safe side: mis-labelled traffic slows itself, never the
    operator's interactive reserve (FRG-META-022)."""
    return LANE_INTERACTIVE if lane == LANE_INTERACTIVE else LANE_BATCH


def effective_interval(settings) -> float:
    """The enforced min-interval: the configured value clamped up to the
    documented floor (with a one-line warning when clamping)."""
    configured = float(settings.comicvine_min_interval_seconds)
    if configured < MIN_INTERVAL_FLOOR:
        logger.warning(
            "comicvine_min_interval_seconds=%s is below the floor %s; clamped",
            configured,
            MIN_INTERVAL_FLOOR,
        )
        return MIN_INTERVAL_FLOOR
    return configured


def effective_budget(settings) -> int:
    """The enforced per-path hourly ceiling (FRG-META-016): the configured value
    clamped into the documented ``BUDGET_FLOOR..BUDGET_CEILING`` range (with a
    one-line warning when clamping), mirroring :func:`effective_interval`.

    An operator may lower the ceiling to leave more headroom for other tools
    sharing the key, but can never raise it above ComicVine's documented
    200/hour/path limit."""
    configured = int(settings.comicvine_hourly_path_budget)
    clamped = min(max(configured, BUDGET_FLOOR), BUDGET_CEILING)
    if clamped != configured:
        logger.warning(
            "comicvine_hourly_path_budget=%s is outside the safe range %s..%s; "
            "clamped to %s",
            configured,
            BUDGET_FLOOR,
            BUDGET_CEILING,
            clamped,
        )
    return clamped


def effective_batch_share(settings) -> float:
    """The enforced batch share of each path budget (FRG-META-022): the
    configured fraction clamped into ``BATCH_SHARE_FLOOR..BATCH_SHARE_CEILING``
    (with a one-line warning when clamping), mirroring :func:`effective_budget`.

    Below the floor, background refresh/enrichment would starve; above the
    ceiling, the interactive reserve stops being a reserve.

    A non-finite value is handled BEFORE the clamp, because NaN survives one:
    every comparison against NaN is false, so ``min(max(nan, floor), ceiling)``
    is still NaN, and the NaN then reaches :func:`batch_ceiling` where
    ``int(budget * nan)`` raises — turning one typo'd env var into a 500 on every
    ComicVine request. Infinities would clamp, but a share of infinity is not an
    intent worth guessing at, so they take the same route: fall back to the
    DECLARED default with a warning, the same correct-and-continue shape as the
    clamp. (``allow_inf_nan=False`` on the field is deliberately NOT used: it
    would make the same typo a hard boot failure, where every sibling ComicVine
    knob corrects-and-warns instead.)"""
    configured = float(settings.comicvine_batch_budget_share)
    if not math.isfinite(configured):
        fallback = _declared_default(
            settings, "comicvine_batch_budget_share", BATCH_SHARE_FALLBACK
        )
        logger.warning(
            "comicvine_batch_budget_share=%s is not a finite number; using the "
            "default %s",
            configured,
            fallback,
        )
        return fallback
    clamped = min(max(configured, BATCH_SHARE_FLOOR), BATCH_SHARE_CEILING)
    if clamped != configured:
        logger.warning(
            "comicvine_batch_budget_share=%s is outside the safe range %s..%s; "
            "clamped to %s",
            configured,
            BATCH_SHARE_FLOOR,
            BATCH_SHARE_CEILING,
            clamped,
        )
    return clamped


def batch_ceiling(budget: int, batch_share: float | None) -> int:
    """The batch-lane admission ceiling for a path budget: ``floor(budget ×
    share)``, or the full ``budget`` when no share is supplied (the
    lane dimension is off, exactly as the budget dimension is off without a
    ``budget=``)."""
    if batch_share is None:
        return budget
    return int(budget * batch_share)


class _Stamp(float):
    """One admitted request: a monotonic timestamp tagged with its lane.

    Subclassing ``float`` rather than storing a ``(timestamp, lane)`` tuple
    keeps the ledger ONE deque of directly comparable timestamps (D1: one
    ledger per bucket, lane-tagged stamps): the prune, the index arithmetic and
    the resume math read a stamp exactly as they did before the lane existed,
    and untagged floats (a test poking the documented ledger surface) still
    read correctly — as batch, per :func:`normalize_lane`.
    """

    __slots__ = ("lane",)

    def __new__(cls, value: float, lane: str = LANE_BATCH) -> "_Stamp":
        # ``lane`` MUST have a default: ``copy``/``pickle`` reconstruct a float
        # subclass by calling ``cls.__new__(cls, value)`` with the numeric value
        # alone, so a required second argument makes a tagged ledger
        # un-copyable (TypeError) — and a deque of stamps is exactly the kind of
        # thing a snapshot/diagnostic helper deep-copies. The lane itself rides
        # the __slots__ state, so a round-trip keeps its tag; anywhere the tag
        # IS lost, arithmetic on a stamp degrades to a plain float, which
        # :func:`_lane_of` reads as batch — fail-frugal, the same default the
        # gate applies to any unclassified caller.
        stamp = super().__new__(cls, value)
        stamp.lane = lane
        return stamp


def _lane_of(stamp: float) -> str:
    """The lane a ledger stamp was admitted on (batch when untagged)."""
    return normalize_lane(getattr(stamp, "lane", None))


class _RateGate:
    """Serializes CV traffic and enforces spacing + back-off cool-downs."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._last: float | None = None
        self._cooldown_until = 0.0
        self._consecutive = 0
        self._degraded = False
        #: Auth-failure dimension (FRG-META-019): flipped on a 401/403 response,
        #: cleared on the next success. Independent of the rate-limit back-off
        #: and budget dimensions — a bad key is not a cool-down.
        self._auth_failed = False
        #: Per-bucket rolling-hour admission ledger (FRG-META-016/022): a deque
        #: of monotonic-clock timestamps TAGGED WITH THE ADMITTING LANE
        #: (:class:`_Stamp`), one appended per ADMITTED request, pruned at
        #: BUDGET_WINDOW_SECONDS. One ledger per bucket serves both the
        #: whole-path view and the batch-lane view, so the two can never
        #: disagree. Bounded by the ceiling, so memory is O(paths × ceiling).
        self._ledgers: dict[str, deque[float]] = {}
        #: The most recently supplied effective ceiling, remembered so the health
        #: snapshot can report usage-vs-ceiling without re-plumbing settings.
        self._budget: int | None = None
        #: The most recently supplied effective batch share, remembered for the
        #: same reason (``None`` = the lane dimension has never been supplied).
        self._batch_share: float | None = None

    @staticmethod
    def _prune(ledger: deque[float], now: float) -> None:
        """Drop admissions older than the rolling window."""
        cutoff = now - BUDGET_WINDOW_SECONDS
        while ledger and ledger[0] <= cutoff:
            ledger.popleft()

    @staticmethod
    def _resume_in(stamps, used: int, limit: int, now: float) -> float:
        """Seconds until ``used`` admissions over ``stamps`` fall below ``limit``.

        The ONE resume calculation, shared by the whole-path and batch-lane views
        and by both the refusal path and the health snapshot — so a refusal's
        ``retry_after_seconds`` and the meter's countdown can never disagree
        about the same constraint.

        ``limit`` of 0 (or negative) admits nothing, so no stamp aging out can
        ever clear it; that reports a full window rather than indexing off the
        end of a ledger that is (necessarily) shorter than the overshoot.
        Otherwise, the stamp at index ``used - limit`` (0-based, oldest first)
        is the one that must age out of the rolling window for the count to
        drop below the limit — using that index rather than the oldest stamp
        keeps the answer honest when a lowered ceiling leaves the ledger
        holding more entries than the limit.
        """
        if limit <= 0:
            return BUDGET_WINDOW_SECONDS
        return max(0.0, stamps[used - limit] + BUDGET_WINDOW_SECONDS - now)

    def _refuse_if_exhausted(
        self,
        bucket: str,
        budget: int,
        now: float,
        *,
        lane: str = LANE_BATCH,
        batch_share: float | None = None,
    ) -> None:
        """Raise the typed refusal when ``bucket`` cannot admit ``lane``.

        Two admission rules over the ONE ledger (FRG-META-016/022):

        * every lane is refused at the full path ceiling — the interactive
          reserve is a floor for interactivity, never an allowance beyond the
          path ceiling;
        * a batch caller is additionally refused once batch-tagged admissions
          reach ``floor(budget × batch_share)``, leaving the remainder as the
          interactive reserve. That refusal is lane-scoped: it names the lane
          and says the reserve remains.

        ``retry_after_seconds`` is a LOWER BOUND: the earliest moment both
        conditions the caller needs could hold, computed as the later of the two
        age-out times (hence ``max``). It is not a promise. The counts are only
        non-increasing while NOTHING is admitted, and a lane-scoped refusal
        leaves the other lane free to keep spending — so an interactive stream
        running through the pause can push the path count back up and defer a
        batch caller past this time. Consumers log it as an estimate; none
        schedules against it."""
        ledger = self._ledgers.setdefault(bucket, deque())
        self._prune(ledger, now)
        used = len(ledger)

        # ``budget`` of 0 admits nothing, so ``used >= budget`` holds on an EMPTY
        # ledger — the shared resume helper reports a full window there rather
        # than indexing nothing.
        blocked_total = used >= budget
        wait_total = self._resume_in(ledger, used, budget, now) if blocked_total else 0.0

        blocked_batch = False
        wait_batch = 0.0
        batch_used = 0
        ceiling = batch_ceiling(budget, batch_share)
        if lane == LANE_BATCH and batch_share is not None:
            batch_stamps = [s for s in ledger if _lane_of(s) == LANE_BATCH]
            batch_used = len(batch_stamps)
            if batch_used >= ceiling:
                blocked_batch = True
                wait_batch = self._resume_in(batch_stamps, batch_used, ceiling, now)

        if not (blocked_total or blocked_batch):
            return

        retry_after = max(wait_total, wait_batch)
        if blocked_total:
            # The whole path is spent — the same refusal FRG-META-016 has
            # always raised, for either lane (no lane named: nothing is
            # reserved for anyone).
            logger.warning(
                "comicvine path budget exhausted for %r (%d/%d in the "
                "last hour, %s lane); refusing locally, resumes in ~%.0fs",
                bucket,
                used,
                budget,
                lane,
                retry_after,
            )
            raise ComicVineBudgetExhausted(
                bucket, retry_after_seconds=retry_after
            )

        logger.warning(
            "comicvine %s share exhausted for path %r (%d/%d of the batch "
            "share, %d/%d overall); refusing locally, the interactive reserve "
            "remains, resumes in ~%.0fs at the earliest",
            LANE_BATCH,
            bucket,
            batch_used,
            ceiling,
            used,
            budget,
            retry_after,
        )
        raise ComicVineBudgetExhausted(
            bucket, retry_after_seconds=retry_after, lane=LANE_BATCH
        )

    async def acquire(
        self,
        min_interval: float,
        *,
        bucket: str | None = None,
        budget: int | None = None,
        lane: str = LANE_BATCH,
        batch_share: float | None = None,
    ) -> None:
        """Block until this caller may issue its request, honoring the
        min-interval spacing and any active back-off cool-down.

        When ``bucket`` and ``budget`` are supplied, the per-path hourly budget
        (FRG-META-016) is enforced FIRST — and BEFORE queueing on the gate
        lock, so an exhausted-path caller is refused immediately even while
        another caller holds the lock sleeping out a spacing interval or a
        429 cool-down (the check has
        no ``await``, so it is atomic on the event loop). The same check
        re-runs under the lock as the authoritative admission decision. A
        refusal raises :class:`ComicVineBudgetExhausted` — no sleep, no wire
        request, and WITHOUT touching the degraded/back-off state (the refusal
        is a purely local decision; ComicVine saw nothing). A timestamp is
        appended to the bucket's ledger only when the request is actually
        admitted (past both the budget check and the spacing/cool-down wait) —
        tagged with the admitting lane.

        ``lane`` declares the priority lane (FRG-META-022) and defaults to
        ``batch``; anything unrecognized is accounted as batch. ``batch_share``
        supplies the batch cap as a fraction of ``budget`` — omitted (``None``)
        it leaves the lane dimension off entirely, the same optional-dimension
        idiom as ``bucket``/``budget``. Production call sites (the client seam
        and the covers cache) always supply it from
        :func:`effective_batch_share`.
        """
        loop = asyncio.get_running_loop()
        lane = normalize_lane(lane)
        if budget is not None:
            self._budget = budget
        if batch_share is not None:
            self._batch_share = batch_share
        if bucket is not None and budget is not None:
            # Fast refusal without waiting on the gate lock.
            self._refuse_if_exhausted(
                bucket,
                budget,
                loop.time(),
                lane=lane,
                batch_share=batch_share,
            )

        async with self._lock:
            now = loop.time()

            # Authoritative re-check under the lock: the fast check above may
            # have admitted a caller whose window state changed while it
            # queued for the lock.
            if bucket is not None and budget is not None:
                self._refuse_if_exhausted(
                    bucket, budget, now, lane=lane, batch_share=batch_share
                )

            wait = 0.0
            if self._last is not None:
                wait = max(wait, min_interval - (now - self._last))
            wait = max(wait, self._cooldown_until - now)
            if wait > 0:
                await asyncio.sleep(wait)
            now = loop.time()
            if now >= self._cooldown_until:
                self._degraded = False
                self._consecutive = 0
            self._last = now
            if bucket is not None:
                self._ledgers.setdefault(bucket, deque()).append(
                    _Stamp(now, lane)
                )

    def budget_health(self) -> tuple[dict[str, dict[str, object]], bool]:
        """The per-path budget snapshot for the health payload (FRG-META-016).

        Returns ``(path_budgets, budget_exhausted)`` where ``path_budgets`` maps
        each REPORTABLE bucket to ``{used, ceiling, batch_used, batch_ceiling,
        approaching, resumes_in_seconds, batch_resumes_in_seconds}`` — so the
        common quiet case is an empty map and the payload stays small — and
        ``budget_exhausted`` is ``True`` when any bucket is at/over its ceiling.

        There are TWO countdowns because there are two walls.
        ``resumes_in_seconds`` is the whole path's: the duration until the bucket
        falls back below its ceiling (0 while it still has headroom).
        ``batch_resumes_in_seconds`` is the batch lane's: the duration until
        background work can spend again (0 while it still can). A bucket can sit
        at the second without being anywhere near the first, which is the ordinary
        state of a nightly enrichment run.

        A bucket is reportable when its usage is AT OR ABOVE the warning
        threshold (≥80% of the ceiling) OR its batch lane has spent its share
        (FRG-META-022) — the batch share (default 70%) sits *below* the warning
        fraction, so a paused batch lane would otherwise be invisible exactly
        when an operator most wants to know why background work stopped.

        Those two admission reasons are DIFFERENT states, so ``approaching``
        publishes which one applies rather than leaving a consumer to infer it
        from membership. Membership stopped meaning "near the ceiling" the moment
        batch-paused buckets joined the map: at the defaults a nightly batch run
        parks a bucket here at 105/150, which is a paused lane, not an
        approaching wall. ``approaching``/``batch_used``/``batch_ceiling`` are
        additive keys: existing consumers of ``used``/``ceiling`` are unaffected.

        Best-effort: with no running loop (no monotonic clock) it reports a
        compact/empty snapshot.
        """
        if self._budget is None:
            return {}, False
        try:
            now = asyncio.get_running_loop().time()
        except RuntimeError:
            return {}, False
        ceiling = self._budget
        share = self._batch_share
        batch_cap = batch_ceiling(ceiling, share)
        threshold = ceiling * BUDGET_WARNING_FRACTION
        budgets: dict[str, dict[str, object]] = {}
        exhausted = False
        for bucket, ledger in self._ledgers.items():
            self._prune(ledger, now)
            used = len(ledger)
            if used == 0:
                continue
            if used >= ceiling:
                exhausted = True
            batch_stamps = [s for s in ledger if _lane_of(s) == LANE_BATCH]
            batch_used = len(batch_stamps)
            batch_paused = share is not None and batch_used >= batch_cap
            approaching = used >= threshold
            if approaching or batch_paused:
                resumes_in = (
                    self._resume_in(ledger, used, ceiling, now)
                    if used >= ceiling
                    else 0.0
                )
                # The batch lane has its own wall and therefore its own
                # countdown. Folding it into ``resumes_in_seconds`` would lie to
                # the exhausted-path message (which means the WHOLE path);
                # leaving it out lies to the meter, which would show a paused
                # lane with no answer to "until when?" — the one question a
                # pause raises. So it is its own key, 0.0 while batch is running.
                batch_resumes_in = (
                    self._resume_in(batch_stamps, batch_used, batch_cap, now)
                    if batch_paused
                    else 0.0
                )
                budgets[bucket] = {
                    "used": used,
                    "ceiling": ceiling,
                    "batch_used": batch_used,
                    "batch_ceiling": batch_cap,
                    "approaching": approaching,
                    "resumes_in_seconds": round(resumes_in, 3),
                    "batch_resumes_in_seconds": round(batch_resumes_in, 3),
                }
        return budgets, exhausted

    def note_rate_limited(self, retry_after: float | None) -> float:
        """Record a rate-limit/ban signal: extend the cool-down to
        ``max(retry_after, exponential backoff)`` and flip degraded. Returns
        the effective delay."""
        self._consecutive += 1
        backoff = min(
            MIN_INTERVAL_FLOOR * (2 ** self._consecutive), MAX_BACKOFF_SECONDS
        )
        delay = max(retry_after or 0.0, backoff)
        try:
            now = asyncio.get_running_loop().time()
        except RuntimeError:  # no loop (defensive) — cool-down is best-effort
            now = 0.0
        self._cooldown_until = max(self._cooldown_until, now + delay)
        self._degraded = True
        logger.warning(
            "comicvine rate-limited; backing off %.1fs (degraded)", delay
        )
        return delay

    def note_auth_failed(self) -> None:
        """Record an authentication rejection (FRG-META-019)."""
        if not self._auth_failed:
            logger.warning(
                "comicvine authentication failed; health marked until the "
                "next successful request"
            )
        self._auth_failed = True

    def note_auth_ok(self) -> None:
        """A successful response clears the auth-failure state."""
        self._auth_failed = False

    def is_auth_failed(self) -> bool:
        return self._auth_failed

    def is_degraded(self) -> bool:
        if not self._degraded:
            return False
        try:
            now = asyncio.get_running_loop().time()
        except RuntimeError:
            return self._degraded
        if now >= self._cooldown_until:
            self._degraded = False
            self._consecutive = 0
        return self._degraded

    def cooldown_remaining(self) -> float:
        try:
            now = asyncio.get_running_loop().time()
        except RuntimeError:
            return 0.0
        return max(0.0, self._cooldown_until - now)


#: The one process-global gate.
_GATE = _RateGate()


def gate() -> _RateGate:
    """Accessor for the process-global rate gate (shared by every call site)."""
    return _GATE


def reset_gate() -> None:
    """Reset the global gate — TEST-ONLY isolation hook."""
    global _GATE
    _GATE = _RateGate()


def comicvine_degraded() -> bool:
    """Whether ComicVine is currently in a backed-off/degraded state."""
    return _GATE.is_degraded()


def comicvine_health() -> dict[str, object]:
    """A small health snapshot the API health endpoint surfaces.

    Shape: ``{"degraded": bool, "cooldown_remaining_seconds": float,
    "path_budgets": {bucket: {used, ceiling, batch_used, batch_ceiling,
    approaching, resumes_in_seconds, batch_resumes_in_seconds}},
    "budget_exhausted": bool,
    "auth_failed": bool}``. ``path_budgets`` lists only buckets at or above the
    80% warning threshold or with a batch lane at its share (empty in the common
    quiet case); ``approaching`` says WHICH of those two a listed bucket is, and
    ``budget_exhausted`` flags a bucket at/over its ceiling (FRG-META-016). The
    budget dimension is INDEPENDENT of ``degraded`` — a local budget refusal
    never flips the rate-limit back-off state.
    ``approaching``/``batch_used``/``batch_ceiling``/``batch_resumes_in_seconds``
    (FRG-META-022) are additive: a consumer reading only ``used``/``ceiling``/
    ``resumes_in_seconds`` keeps working unchanged.
    """
    path_budgets, budget_exhausted = _GATE.budget_health()
    return {
        "degraded": _GATE.is_degraded(),
        "cooldown_remaining_seconds": round(_GATE.cooldown_remaining(), 3),
        "path_budgets": path_budgets,
        "budget_exhausted": budget_exhausted,
        "auth_failed": _GATE.is_auth_failed(),
    }
