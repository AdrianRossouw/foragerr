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
    """Serializes and spaces requests to one indexer.

    Two classes of waiter share the gate (FRG-SRCH-015): ``priority`` ones (a
    person is waiting on an interactive search behind the listener's request
    guard) and ordinary background ones (an add sweep, the backlog walk). A
    priority waiter takes the gate's NEXT politeness slot ahead of any waiting
    background acquire — otherwise a sweep with N requests queued on one
    indexer makes the operator wait N politeness slots and their search returns
    starved-empty.

    Precedence is a *yield*, never a spacing exemption: the slot itself is
    still whatever ``min_interval`` says, so the outbound request rate to an
    indexer is exactly what it was before priority existed. Only the ORDER of
    waiters changes.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._last: float | None = None
        #: How many priority acquires are in flight (waiting or being admitted).
        self._priority_waiters = 0
        #: Set exactly while ``_priority_waiters == 0`` — what background
        #: waiters park on instead of contending for the lock.
        self._drained = asyncio.Event()
        self._drained.set()
        #: The exact complement of ``_drained``: set while priority demand
        #: exists. A background waiter already sleeping out a slot races its
        #: sleep against this, so the slot it was waiting for goes to the
        #: interactive request instead of to it.
        self._pending = asyncio.Event()

    async def acquire(self, min_interval: float, *, priority: bool = False) -> None:
        if priority:
            # Announce the demand BEFORE contending for the lock, so background
            # waiters (including ones already queued on the lock) stand down.
            # No await between the increment and the ``try``, so a cancellation
            # can never land in the window and leak the count.
            self._priority_waiters += 1
            self._drained.clear()
            self._pending.set()
            try:
                await self._admit(min_interval)
            finally:
                self._priority_waiters -= 1
                if self._priority_waiters <= 0:
                    self._priority_waiters = 0
                    self._pending.clear()
                    self._drained.set()
            return

        while True:
            # Park (cheaply, no lock held) while any priority demand exists...
            while self._priority_waiters:
                await self._drained.wait()
            # ...and re-check under the lock, because the demand may have
            # arrived while this waiter sat in the lock's own FIFO queue. Losing
            # the lock again costs nothing (no sleep has happened yet) and the
            # loop puts this waiter straight back on the event.
            if await self._admit(min_interval, yield_to_priority=True):
                return

    async def _admit(
        self, min_interval: float, *, yield_to_priority: bool = False
    ) -> bool:
        """Take the gate's next slot, sleeping out the remaining spacing.

        Returns ``False``, having stamped nothing, when a background waiter
        meets priority demand — either already present when it takes the lock,
        or arriving while it sleeps out the slot. Giving up the slot MID-SLEEP
        is what makes precedence worth having: otherwise every interactive
        request waits for the background sleeper to take the slot first and
        then a whole further interval of its own, doubling the cost of every
        page of an interactive search that runs against a busy sweep.

        Abandoning costs the gate nothing and the operator's politeness nothing:
        no timestamp is written, so the priority waiter that follows still
        measures its own wait from the last request that REALLY went out.
        """
        async with self._lock:
            if yield_to_priority and self._priority_waiters:
                return False
            loop = asyncio.get_running_loop()
            now = loop.time()
            if self._last is not None:
                wait = min_interval - (now - self._last)
                if wait > 0:
                    if yield_to_priority:
                        if await self._sleep_unless_priority(wait):
                            return False
                    else:
                        await asyncio.sleep(wait)
                    now = loop.time()
            # Stamped only AFTER the sleep: a cancelled acquire leaves the
            # spacing measured from the request that really went out.
            self._last = now
            return True

    async def _sleep_unless_priority(self, wait: float) -> bool:
        """Sleep ``wait`` seconds; return ``True`` if priority demand arrived.

        ``wait_for`` on the pending-demand event is just an interruptible
        sleep: the timeout is the normal path (nothing arrived) and a set event
        is the interruption. Cancellation of the acquiring task propagates as
        usual — ``wait_for`` cancels its inner wait and re-raises."""
        try:
            await asyncio.wait_for(self._pending.wait(), timeout=wait)
        except TimeoutError:
            return False  # slept the whole slot undisturbed
        return True


#: One gate per indexer id (created on first use).
_GATES: dict[int, _IndexerGate] = {}


def _gate_for(indexer_id: int) -> _IndexerGate:
    gate = _GATES.get(indexer_id)
    if gate is None:
        gate = _IndexerGate()
        _GATES[indexer_id] = gate
    return gate


async def acquire(
    indexer_id: int,
    min_interval: float = DEFAULT_MIN_INTERVAL,
    *,
    priority: bool = False,
) -> None:
    """Block until a request to ``indexer_id`` may go out, honoring the minimum
    spacing for THAT indexer only (independent of other indexers).

    ``priority`` marks an interactive request: it is admitted at the next
    politeness slot ahead of waiting background requests (FRG-SRCH-015). The
    spacing itself is unchanged — precedence reorders waiters, it never lets a
    request out early."""
    interval = max(min_interval, MIN_INTERVAL_FLOOR)
    await _gate_for(indexer_id).acquire(interval, priority=priority)


def reset_gates() -> None:
    """Forget all per-indexer gates — TEST-ONLY isolation hook."""
    _GATES.clear()
