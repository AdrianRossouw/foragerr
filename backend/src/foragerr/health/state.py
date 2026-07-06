"""In-memory database-integrity health state (FRG-DB-012 / FRG-NFR-011).

The result of the most recent integrity check is held in one process-global
slot, written by the startup ``quick_check`` hook and by the pre-backup full
``integrity_check`` (both in ``db/``), and read by the health-aggregation
service for the ``database`` component. Deliberately process-memory, not a
table (FRG-NFR-011 "no new tracking table"): a check runs at startup and before
each backup, so a fresh process always has a current reading, and a failure
clears on the next clean check without a restart. Mirrors the module-global
pattern of ``metadata/ratelimit.py``.
"""

from __future__ import annotations

import datetime as dt
import threading
from dataclasses import dataclass

from foragerr.db.base import utcnow


@dataclass(frozen=True)
class DatabaseIntegrityState:
    """The most recent integrity-check reading for the ``database`` component."""

    ok: bool
    #: Which check produced it: ``"quick_check"`` or ``"integrity_check"``.
    check: str
    #: Where it ran: ``"startup"`` or ``"pre-backup"``.
    source: str
    checked_at: dt.datetime
    #: Failure detail (a health message), or ``None`` on a clean check.
    detail: str | None = None


_lock = threading.Lock()
_state: DatabaseIntegrityState | None = None


def record_integrity(
    *, ok: bool, check: str, source: str, detail: str | None = None
) -> DatabaseIntegrityState:
    """Store the latest integrity reading; a clean reading clears any error."""
    global _state
    reading = DatabaseIntegrityState(
        ok=ok,
        check=check,
        source=source,
        checked_at=utcnow(),
        detail=None if ok else detail,
    )
    with _lock:
        _state = reading
    return reading


def current_integrity() -> DatabaseIntegrityState | None:
    """The latest integrity reading, or ``None`` if no check has run yet."""
    with _lock:
        return _state


def reset_integrity() -> None:
    """Clear the stored reading — TEST-ONLY isolation hook."""
    global _state
    with _lock:
        _state = None


__all__ = [
    "DatabaseIntegrityState",
    "current_integrity",
    "record_integrity",
    "reset_integrity",
]
