"""Per-source request-spacing gate (FRG-NFR-005).

A minimum interval (default 2 s) is enforced between consecutive HTTP requests
to the *same* store source, including across the order-list → order-detail fan.
Each source gets its own asyncio gate keyed by row id, so a busy source never
delays a different one. Module-global by design — spacing must hold no matter
how many client instances exist, mirroring :mod:`foragerr.indexers.ratelimit`.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger("foragerr.sources.ratelimit")

#: Default minimum seconds between two requests to one source (FRG-NFR-005).
DEFAULT_MIN_INTERVAL = 2.0

#: Absolute floor: an operator cannot drive one source faster than this.
MIN_INTERVAL_FLOOR = 0.1


class _SourceGate:
    """Serializes and spaces requests to one source."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._last: float | None = None

    async def acquire(self, min_interval: float) -> None:
        async with self._lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            if self._last is not None:
                wait = min_interval - (now - self._last)
                if wait > 0:
                    await asyncio.sleep(wait)
                    now = loop.time()
            self._last = now


#: One gate per source id (created on first use).
_GATES: dict[int, _SourceGate] = {}


def _gate_for(source_id: int) -> _SourceGate:
    gate = _GATES.get(source_id)
    if gate is None:
        gate = _SourceGate()
        _GATES[source_id] = gate
    return gate


async def acquire(source_id: int, min_interval: float = DEFAULT_MIN_INTERVAL) -> None:
    """Block until a request to ``source_id`` may go out, honoring the minimum
    spacing for THAT source only (independent of other sources)."""
    interval = max(min_interval, MIN_INTERVAL_FLOOR)
    await _gate_for(source_id).acquire(interval)


def reset_gates() -> None:
    """Forget all per-source gates — TEST-ONLY isolation hook."""
    _GATES.clear()
