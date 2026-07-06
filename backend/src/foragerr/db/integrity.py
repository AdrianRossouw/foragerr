"""SQLite integrity checks (FRG-DB-012).

Two synchronous checks over a database file:

- :func:`run_quick_check` — ``PRAGMA quick_check``: fast, bounded, run at
  startup so a grossly corrupt database is surfaced without blowing the
  startup-time NFR.
- :func:`run_full_integrity_check` — ``PRAGMA integrity_check``: the thorough
  check, run as the first step of every scheduled backup so a corrupt database
  is never rotated into the backup pool.

Both open the file read-only (``mode=ro``) so a check never mutates the
database it is inspecting, and both return an :class:`IntegrityResult` rather
than raising on corruption — the caller decides whether corruption gates a
backup (FRG-DB-009), fails a restore (FRG-DB-010), or marks a health error
(FRG-NFR-011). An operational failure (file missing, unreadable) is reported as
a non-ok result too, never swallowed.

Everything here is stdlib ``sqlite3`` and synchronous; async callers run it via
``asyncio.to_thread``.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

#: The single-row answer SQLite returns from a passing quick/integrity check.
_OK = "ok"


@dataclass(frozen=True)
class IntegrityResult:
    """The outcome of one integrity check over a database file."""

    ok: bool
    check: str  # "quick_check" | "integrity_check"
    #: The problem rows SQLite reported (empty when ok), or a single operational
    #: error string when the file could not be checked at all.
    errors: tuple[str, ...] = ()

    @property
    def detail(self) -> str:
        """A short human-readable summary suitable for a health message/log."""
        if self.ok:
            return f"{self.check}: ok"
        if not self.errors:  # pragma: no cover - defensive
            return f"{self.check}: failed"
        head = "; ".join(self.errors[:3])
        more = f" (+{len(self.errors) - 3} more)" if len(self.errors) > 3 else ""
        return f"{self.check}: {head}{more}"


def _run(db_path: Path, pragma: str, check: str) -> IntegrityResult:
    if not Path(db_path).exists():
        return IntegrityResult(
            ok=False, check=check, errors=(f"database file {db_path} does not exist",)
        )
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        return IntegrityResult(
            ok=False, check=check, errors=(f"cannot open {db_path}: {exc}",)
        )
    try:
        rows = conn.execute(pragma).fetchall()
    except sqlite3.DatabaseError as exc:
        # A malformed image can fail the PRAGMA itself ("database disk image is
        # malformed"); that IS a corruption signal, not a clean pass.
        return IntegrityResult(ok=False, check=check, errors=(str(exc),))
    finally:
        conn.close()

    messages = [str(r[0]) for r in rows if r and r[0] is not None]
    if messages == [_OK]:
        return IntegrityResult(ok=True, check=check)
    return IntegrityResult(ok=False, check=check, errors=tuple(messages))


def run_quick_check(db_path: Path) -> IntegrityResult:
    """``PRAGMA quick_check`` — the fast startup check (FRG-DB-012)."""
    return _run(Path(db_path), "PRAGMA quick_check", "quick_check")


def run_full_integrity_check(db_path: Path) -> IntegrityResult:
    """``PRAGMA integrity_check`` — the thorough pre-backup check (FRG-DB-012)."""
    return _run(Path(db_path), "PRAGMA integrity_check", "integrity_check")


__all__ = [
    "IntegrityResult",
    "run_full_integrity_check",
    "run_quick_check",
]
