"""GetComics fetch politeness: persisted spacing + jitter (FRG-DDL-006).

Search-page fetches are spaced at least a configurable minimum interval apart
(default 15 s, clamped) with random jitter, and the per-provider last-run + hit
statistics survive a restart so foragerr does not hammer the site immediately
after coming back up.

Persistence uses a tiny JSON state file per provider under
``<config>/ddl-state/`` rather than a new table (the change's single migration
is fixed; §M1 constraint). Within a process a module-global lock per provider
serializes the gate so concurrent fetches cannot both skip the wait; across a
restart the persisted ``last_run`` re-imposes the interval.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from foragerr.db.base import utcnow

logger = logging.getLogger("foragerr.ddl.politeness")

#: Absolute floor the configured interval is clamped UP to (FRG-DDL-006).
MIN_INTERVAL_FLOOR = 15.0

#: Maximum extra jitter (seconds) added on top of the interval.
JITTER_MAX_SECONDS = 5.0

_locks: dict[int, asyncio.Lock] = {}


def _lock_for(provider_id: int) -> asyncio.Lock:
    lock = _locks.get(provider_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[provider_id] = lock
    return lock


def reset_locks() -> None:
    """Forget all per-provider gate locks — TEST-ONLY isolation hook."""
    _locks.clear()


@dataclass(frozen=True, slots=True)
class ProviderStats:
    """Persisted per-provider fetch statistics (FRG-DDL-006)."""

    last_run: dt.datetime | None
    hits: int


def _state_path(config_dir: Path, provider_id: int) -> Path:
    return Path(config_dir) / "ddl-state" / f"provider-{provider_id}.json"


def load_stats(config_dir: Path, provider_id: int) -> ProviderStats:
    """Read the persisted stats for one provider (missing/corrupt → empty)."""
    path = _state_path(config_dir, provider_id)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        return ProviderStats(last_run=None, hits=0)
    last_raw = raw.get("last_run")
    last: dt.datetime | None = None
    if isinstance(last_raw, str):
        try:
            last = dt.datetime.fromisoformat(last_raw)
        except ValueError:
            last = None
    hits = raw.get("hits")
    return ProviderStats(last_run=last, hits=hits if isinstance(hits, int) else 0)


def save_stats(config_dir: Path, provider_id: int, stats: ProviderStats) -> None:
    """Persist stats for one provider (best-effort; a write failure is logged
    but never fails a search)."""
    path = _state_path(config_dir, provider_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "last_run": stats.last_run.isoformat()
                    if stats.last_run is not None
                    else None,
                    "hits": stats.hits,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning("ddl: could not persist provider stats: %s", exc)


async def throttle(
    config_dir: Path,
    provider_id: int,
    *,
    min_interval: float,
    jitter_max: float = JITTER_MAX_SECONDS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    clock: Callable[[], dt.datetime] = utcnow,
    rand: Callable[[], float] = random.random,
) -> ProviderStats:
    """Enforce the spaced+jittered gate before a page fetch (FRG-DDL-006).

    Sleeps until at least ``min_interval`` (clamped up to the floor) plus jitter
    has elapsed since the persisted ``last_run``, then records this fetch and
    persists the updated stats. Returns the new stats. ``sleep``/``clock``/
    ``rand`` are injectable so tests assert spacing + jitter deterministically
    without real waits.
    """
    interval = max(min_interval, MIN_INTERVAL_FLOOR)
    async with _lock_for(provider_id):
        stats = load_stats(config_dir, provider_id)
        now = clock()
        jitter = rand() * max(0.0, jitter_max)
        if stats.last_run is not None:
            elapsed = (now - stats.last_run).total_seconds()
            wait = interval - elapsed + jitter
        else:
            wait = jitter  # first-ever fetch: only jitter, no full interval
        if wait > 0:
            await sleep(wait)
            now = clock()
        updated = ProviderStats(last_run=now, hits=stats.hits + 1)
        save_stats(config_dir, provider_id, updated)
        return updated


__all__ = [
    "JITTER_MAX_SECONDS",
    "MIN_INTERVAL_FLOOR",
    "ProviderStats",
    "load_stats",
    "reset_locks",
    "save_stats",
    "throttle",
]
