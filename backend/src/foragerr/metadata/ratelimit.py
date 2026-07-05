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

logger = logging.getLogger("foragerr.metadata.ratelimit")

#: Absolute safety floor for the configured min-interval. An operator cannot
#: drive ComicVine faster than this regardless of configuration.
MIN_INTERVAL_FLOOR = 0.25

#: Exponential-backoff ceiling on repeated rate-limit signals.
MAX_BACKOFF_SECONDS = 300.0


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


class _RateGate:
    """Serializes CV traffic and enforces spacing + back-off cool-downs."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._last: float | None = None
        self._cooldown_until = 0.0
        self._consecutive = 0
        self._degraded = False

    async def acquire(self, min_interval: float) -> None:
        """Block until this caller may issue its request, honoring both the
        min-interval spacing and any active back-off cool-down."""
        async with self._lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
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
    """A small health snapshot the API health endpoint can surface later.

    Shape: ``{"degraded": bool, "cooldown_remaining_seconds": float}``.
    """
    return {
        "degraded": _GATE.is_degraded(),
        "cooldown_remaining_seconds": round(_GATE.cooldown_remaining(), 3),
    }
