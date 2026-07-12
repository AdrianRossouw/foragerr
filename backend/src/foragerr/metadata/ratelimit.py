"""Process-global ComicVine rate limiter (FRG-META-003, FRG-NFR-004).

ONE asyncio token gate serializes every ComicVine request in the process —
search, volume, issue pagination AND cover fetches — so observed inter-request
wire times never fall below the configured minimum interval (default 2 s).
Mylar's blind per-call sleep and unlocked concurrency are the anti-patterns
this replaces: concurrent callers queue on the gate rather than bursting.

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


class _RateGate:
    """Serializes CV traffic and enforces spacing + back-off cool-downs."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._last: float | None = None
        self._cooldown_until = 0.0
        self._consecutive = 0
        self._degraded = False
        #: Per-bucket rolling-hour admission ledger (FRG-META-016): a deque of
        #: monotonic-clock timestamps, one appended per ADMITTED request, pruned
        #: at BUDGET_WINDOW_SECONDS. Bounded by the ceiling, so memory is
        #: O(paths × ceiling).
        self._ledgers: dict[str, deque[float]] = {}
        #: The most recently supplied effective ceiling, remembered so the health
        #: snapshot can report usage-vs-ceiling without re-plumbing settings.
        self._budget: int | None = None

    @staticmethod
    def _prune(ledger: deque[float], now: float) -> None:
        """Drop admissions older than the rolling window."""
        cutoff = now - BUDGET_WINDOW_SECONDS
        while ledger and ledger[0] <= cutoff:
            ledger.popleft()

    def _refuse_if_exhausted(self, bucket: str, budget: int, now: float) -> None:
        """Raise the typed refusal when ``bucket`` is at its ceiling.

        ``retry_after_seconds`` is the time until the bucket next falls BELOW
        the ceiling — the admission at index ``len - budget`` must age out,
        which matches :meth:`budget_health`'s ``resumes_in_seconds`` even when
        a lowered ceiling leaves the ledger holding more than ``budget``
        entries (gate finding, cv-budget-caching review).
        """
        ledger = self._ledgers.setdefault(bucket, deque())
        self._prune(ledger, now)
        if len(ledger) >= budget:
            retry_after = max(
                0.0,
                ledger[len(ledger) - budget] + BUDGET_WINDOW_SECONDS - now,
            )
            logger.warning(
                "comicvine path budget exhausted for %r (%d/%d in the "
                "last hour); refusing locally, resumes in ~%.0fs",
                bucket,
                len(ledger),
                budget,
                retry_after,
            )
            raise ComicVineBudgetExhausted(
                bucket, retry_after_seconds=retry_after
            )

    async def acquire(
        self,
        min_interval: float,
        *,
        bucket: str | None = None,
        budget: int | None = None,
    ) -> None:
        """Block until this caller may issue its request, honoring the
        min-interval spacing and any active back-off cool-down.

        When ``bucket`` and ``budget`` are supplied, the per-path hourly budget
        (FRG-META-016) is enforced FIRST — and BEFORE queueing on the gate
        lock, so an exhausted-path caller is refused immediately even while
        another caller holds the lock sleeping out a spacing interval or a
        429 cool-down (gate finding, cv-budget-caching review; the check has
        no ``await``, so it is atomic on the event loop). The same check
        re-runs under the lock as the authoritative admission decision. A
        refusal raises :class:`ComicVineBudgetExhausted` — no sleep, no wire
        request, and WITHOUT touching the degraded/back-off state (the refusal
        is a purely local decision; ComicVine saw nothing). A timestamp is
        appended to the bucket's ledger only when the request is actually
        admitted (past both the budget check and the spacing/cool-down wait).
        """
        loop = asyncio.get_running_loop()
        if budget is not None:
            self._budget = budget
        if bucket is not None and budget is not None:
            # Fast refusal without waiting on the gate lock.
            self._refuse_if_exhausted(bucket, budget, loop.time())

        async with self._lock:
            now = loop.time()

            # Authoritative re-check under the lock: the fast check above may
            # have admitted a caller whose window state changed while it
            # queued for the lock.
            if bucket is not None and budget is not None:
                self._refuse_if_exhausted(bucket, budget, now)

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
                self._ledgers.setdefault(bucket, deque()).append(now)

    def budget_health(self) -> tuple[dict[str, dict[str, object]], bool]:
        """The per-path budget snapshot for the health payload (FRG-META-016).

        Returns ``(path_budgets, budget_exhausted)`` where ``path_budgets`` maps
        each bucket AT OR ABOVE the warning threshold (≥80% of the ceiling) to
        ``{used, ceiling, resumes_in_seconds}`` — so the common quiet case is an
        empty map and the payload stays small — and ``budget_exhausted`` is
        ``True`` when any bucket is at/over its ceiling. ``resumes_in_seconds``
        is the duration until the bucket next falls below the ceiling (0 while it
        still has headroom). Best-effort: with no running loop (no monotonic
        clock) it reports a compact/empty snapshot.
        """
        if self._budget is None:
            return {}, False
        try:
            now = asyncio.get_running_loop().time()
        except RuntimeError:
            return {}, False
        ceiling = self._budget
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
            if used >= threshold:
                if used >= ceiling:
                    # The admission at index (used - ceiling) must age out before
                    # the bucket drops back below the ceiling.
                    resumes_in = max(
                        0.0, ledger[used - ceiling] + BUDGET_WINDOW_SECONDS - now
                    )
                else:
                    resumes_in = 0.0
                budgets[bucket] = {
                    "used": used,
                    "ceiling": ceiling,
                    "resumes_in_seconds": round(resumes_in, 3),
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
    "path_budgets": {bucket: {used, ceiling, resumes_in_seconds}},
    "budget_exhausted": bool}``. ``path_budgets`` lists only buckets at or above
    the 80% warning threshold (empty in the common quiet case), and
    ``budget_exhausted`` flags a bucket at/over its ceiling (FRG-META-016). The
    budget dimension is INDEPENDENT of ``degraded`` — a local budget refusal
    never flips the rate-limit back-off state.
    """
    path_budgets, budget_exhausted = _GATE.budget_health()
    return {
        "degraded": _GATE.is_degraded(),
        "cooldown_remaining_seconds": round(_GATE.cooldown_remaining(), 3),
        "path_budgets": path_budgets,
        "budget_exhausted": budget_exhausted,
    }
