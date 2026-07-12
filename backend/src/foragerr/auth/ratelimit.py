"""Failed-authentication rate limiting with escalating backoff (FRG-AUTH-009).

In-process sliding-window counters over *failed* authentication attempts, keyed
per (client IP, surface). After :data:`FAILURE_THRESHOLD` failures within
:data:`WINDOW_SECONDS`, further attempts on that key are refused *before any
password-hash work* with a deadline that grows exponentially per excess failure
(base :data:`BACKOFF_BASE_SECONDS`, doubling, capped at the window length). The
refusal is temporary — no hard lockout: once the deadline passes the key gets a
fresh attempt, and a success resets its counter. Requests carrying no credential
never reach here (cookie/absent-credential paths are exempt by design).

A second, per-surface *global* counter is observation-only: it never blocks (an
attacker must not be able to lock the operator out by spraying failures from
spoofed sources), but crossing its threshold reports the escalation so a
distributed pattern is visible in the audit log (``auth.backoff_triggered``).

Counters are process-local, ``time.monotonic()``-based (immune to wall-clock
jumps), and reset on restart — accepted for the threat model (restart cadence ≪
window) and it avoids a migration. The registry is bounded (:data:`REGISTRY_
CAPACITY` keys, oldest-idle eviction) so source spraying cannot grow memory
without limit — mirrors the OPDS verify-cache's bounded-size discipline. Lives on
``app.state`` (per-app, not module-global) so tests stay isolated; ``clock`` is
injectable like :class:`foragerr.auth.perimeter.OpdsVerifyCache`.
"""

from __future__ import annotations

import time
from collections import OrderedDict, deque
from typing import Callable, Deque

#: Failures within the window before a key is throttled (per (IP, surface)).
FAILURE_THRESHOLD = 5
#: Sliding-window length in seconds (15 minutes). Also the backoff deadline cap.
WINDOW_SECONDS = 15 * 60
#: First refusal deadline; doubles per failure beyond the threshold, up to the
#: window length.
BACKOFF_BASE_SECONDS = 30.0
#: Distinct (IP, surface) keys retained before oldest-idle eviction.
REGISTRY_CAPACITY = 1024

#: Surface identifiers — the three credential-bearing paths.
SURFACE_LOGIN = "login"
SURFACE_API_KEY = "api_key"
SURFACE_BASIC = "basic"


class RateLimiter:
    """Sliding-window failed-auth counters with exponential backoff.

    Two families in one instance: the enforcing per-(IP, surface) windows and
    the observation-only per-surface global windows. Not thread-safe by design —
    the app runs one event loop and the operations are non-awaiting, so no lock
    is needed (same posture as the verify-cache)."""

    def __init__(
        self,
        *,
        threshold: int = FAILURE_THRESHOLD,
        window_seconds: float = WINDOW_SECONDS,
        backoff_base_seconds: float = BACKOFF_BASE_SECONDS,
        capacity: int = REGISTRY_CAPACITY,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._threshold = threshold
        self._window = window_seconds
        self._backoff_base = backoff_base_seconds
        self._capacity = capacity
        self._clock = clock
        #: (ip, surface) -> deque of monotonic failure timestamps, newest last.
        #: OrderedDict so the least-recently-touched key evicts first.
        self._windows: "OrderedDict[tuple[str, str], Deque[float]]" = OrderedDict()
        #: surface -> deque of monotonic failure timestamps (never blocks).
        self._global: dict[str, Deque[float]] = {}
        #: surface -> whether the global window is currently above threshold, so
        #: ``auth.backoff_triggered`` fires only on the rising edge, not on every
        #: subsequent failure while the window stays hot.
        self._global_hot: dict[str, bool] = {}

    def _prune(self, dq: Deque[float], now: float) -> None:
        """Drop timestamps that have aged out of the window (oldest first)."""
        cutoff = now - self._window
        while dq and dq[0] <= cutoff:
            dq.popleft()

    def retry_after(self, ip: str, surface: str) -> float | None:
        """Seconds a throttled key must wait, or ``None`` when it may attempt now.

        Called BEFORE any KDF work. Pruning ages out old failures, so a key whose
        failures have all left the window is no longer throttled. When the count
        is at/above threshold, the deadline runs from the LAST failure and grows
        exponentially with each excess failure — once it passes the key gets one
        fresh attempt (which, if it fails, doubles the next deadline)."""
        key = (ip, surface)
        dq = self._windows.get(key)
        if dq is None:
            return None
        now = self._clock()
        self._prune(dq, now)
        if not dq:
            return None
        self._windows.move_to_end(key)  # touch: least-idle
        if len(dq) < self._threshold:
            return None
        excess = len(dq) - self._threshold
        deadline = min(self._backoff_base * (2**excess), self._window)
        remaining = dq[-1] + deadline - now
        return remaining if remaining > 0 else None

    def record_failure(self, ip: str, surface: str) -> bool:
        """Register a credential-bearing failure on this key.

        Returns ``True`` iff the per-surface global counter just crossed its
        threshold (rising edge) — the caller emits ``auth.backoff_triggered``.
        Only failures that carry a wrong credential call this; credential-less
        requests never do."""
        now = self._clock()
        key = (ip, surface)
        dq = self._windows.get(key)
        if dq is None:
            dq = deque()
            self._windows[key] = dq
        dq.append(now)
        self._prune(dq, now)
        self._windows.move_to_end(key)
        self._evict()
        return self._record_global(surface, now)

    def record_success(self, ip: str, surface: str) -> None:
        """Reset the enforcing counter for this key (a success clears the burst).

        The global observation counter is intentionally untouched — a legitimate
        success does not erase evidence of a distributed pattern."""
        self._windows.pop((ip, surface), None)

    def _record_global(self, surface: str, now: float) -> bool:
        dq = self._global.get(surface)
        if dq is None:
            dq = deque()
            self._global[surface] = dq
        dq.append(now)
        self._prune(dq, now)
        hot = len(dq) >= self._threshold
        was_hot = self._global_hot.get(surface, False)
        self._global_hot[surface] = hot
        return hot and not was_hot

    def _evict(self) -> None:
        """Bound the registry: drop oldest-idle keys past the capacity."""
        while len(self._windows) > self._capacity:
            self._windows.popitem(last=False)


class SeenSourceSet:
    """TTL'd, bounded set of source IPs that have successfully used the API key.

    Turns per-request key successes (a programmatic client hits every endpoint —
    per-request success events would be pure noise) into one
    ``auth.apikey_source_seen`` event per source per window: :meth:`observe`
    returns ``True`` only for the FIRST successful use from an IP inside the
    window, so a leaked key used from a new address surfaces in the audit trail
    at near-zero volume. Entries expire after :data:`WINDOW_SECONDS`; the set is
    bounded like the counter registry (oldest-idle eviction) so source spraying
    cannot grow memory; :meth:`clear` (called on key rotation) gives a rotated
    key a fresh baseline. Same injectable monotonic clock as :class:`RateLimiter`.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = WINDOW_SECONDS,
        capacity: int = REGISTRY_CAPACITY,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._capacity = capacity
        self._clock = clock
        #: ip -> expiry timestamp. Ordered by last observation; since the TTL is
        #: constant, that order is also expiry order, so the front expires first.
        self._seen: "OrderedDict[str, float]" = OrderedDict()

    def _prune(self, now: float) -> None:
        while self._seen:
            ip, expiry = next(iter(self._seen.items()))
            if expiry <= now:
                del self._seen[ip]
            else:
                break

    def observe(self, ip: str) -> bool:
        """Record a successful key use from ``ip``; ``True`` iff first this window."""
        now = self._clock()
        self._prune(now)
        fresh = ip not in self._seen  # expired entries were just pruned
        self._seen[ip] = now + self._ttl
        self._seen.move_to_end(ip)
        while len(self._seen) > self._capacity:
            self._seen.popitem(last=False)
        return fresh

    def clear(self) -> None:
        """Forget every seen source (called on key rotation for a fresh baseline)."""
        self._seen.clear()


__all__ = [
    "BACKOFF_BASE_SECONDS",
    "FAILURE_THRESHOLD",
    "REGISTRY_CAPACITY",
    "SURFACE_API_KEY",
    "SURFACE_BASIC",
    "SURFACE_LOGIN",
    "WINDOW_SECONDS",
    "RateLimiter",
    "SeenSourceSet",
]
