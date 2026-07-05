"""Per-indexer request-spacing gate (FRG-IDX-008, FRG-NFR-005).

A minimum interval (default 2 s) is enforced between consecutive HTTP requests
to the *same* indexer, including across paging. Each indexer gets its own
asyncio gate keyed by row id, so a busy indexer never delays requests to a
different one (the gates are independent). The gates are module-global by
design — spacing must hold no matter how many client instances exist, mirroring
the ComicVine rate limiter (:mod:`foragerr.metadata.ratelimit`).
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger("foragerr.indexers.ratelimit")

#: Default minimum seconds between two requests to one indexer (FRG-IDX-008).
DEFAULT_MIN_INTERVAL = 2.0

#: Absolute floor: an operator cannot drive one indexer faster than this.
MIN_INTERVAL_FLOOR = 0.1


class _IndexerGate:
    """Serializes and spaces requests to one indexer."""

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


#: One gate per indexer id (created on first use).
_GATES: dict[int, _IndexerGate] = {}


def _gate_for(indexer_id: int) -> _IndexerGate:
    gate = _GATES.get(indexer_id)
    if gate is None:
        gate = _IndexerGate()
        _GATES[indexer_id] = gate
    return gate


async def acquire(indexer_id: int, min_interval: float = DEFAULT_MIN_INTERVAL) -> None:
    """Block until a request to ``indexer_id`` may go out, honoring the minimum
    spacing for THAT indexer only (independent of other indexers)."""
    interval = max(min_interval, MIN_INTERVAL_FLOOR)
    await _gate_for(indexer_id).acquire(interval)


def reset_gates() -> None:
    """Forget all per-indexer gates — TEST-ONLY isolation hook."""
    _GATES.clear()
