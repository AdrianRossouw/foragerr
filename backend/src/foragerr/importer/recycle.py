"""Recycle-bin housekeeping: quarantine→recycle sweep + retention prune (FRG-PP-013).

Two idempotent housekeeping steps (design decision 7), driven from the periodic
``housekeeping`` command:

- :func:`sweep_quarantine_to_recycle` — a one-shot migration of any files left
  under M1's ``<config>/quarantine/<date>/`` stand-in into the configured recycle
  bin, recording each move on a history event. Idempotent (a moved file is gone
  from quarantine, so a re-run finds nothing) and a no-op when no bin is
  configured (the quarantine dir is retired in place, never deleted — nothing is
  lost).
- :func:`prune_recycle_bin` — thin async wrapper over
  :func:`foragerr.importer.fileops.prune_recycle_bin`, permanently removing bin
  entries older than the retention window (``0`` = keep forever).
"""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path

from foragerr.db import Database, utcnow
from foragerr.importer import fileops, history

logger = logging.getLogger("foragerr.importer.recycle")

_QUARANTINE_DIRNAME = "quarantine"


async def sweep_quarantine_to_recycle(
    db: Database,
    *,
    config_dir: str,
    recycle_bin_path: str,
    now: dt.datetime | None = None,
) -> int:
    """Move any leftover M1 quarantine files into the recycle bin (FRG-PP-013).

    Returns the number of files swept. With no bin configured, the quarantine dir
    is left retired-in-place (returns 0). Idempotent: once a file is moved it is
    gone from quarantine, so a re-run sweeps nothing.
    """
    if not recycle_bin_path:
        return 0
    quarantine_root = Path(config_dir) / _QUARANTINE_DIRNAME
    if not quarantine_root.is_dir():
        return 0
    now = now or utcnow()

    swept = 0
    for source in sorted(p for p in quarantine_root.rglob("*") if p.is_file()):
        dest = fileops.recycle_file(source, recycle_bin_path, now=now)
        async with db.write_session() as session:
            history.record_event(
                session,
                event_type=history.EVENT_FILE_DELETED,
                data={
                    "swept_from_quarantine": str(source),
                    "recycle_path": str(dest),
                },
                quarantine_path=str(dest),
                now=now,
            )
        swept += 1

    # Remove the now-empty dated folders left behind (best-effort tidy-up).
    for child in sorted(quarantine_root.iterdir(), reverse=True):
        if child.is_dir():
            try:
                child.rmdir()
            except OSError:
                pass  # still holds files (raced) — leave it, nothing is lost

    if swept:
        logger.info("recycle: swept %d quarantined file(s) into the recycle bin", swept)
    return swept


async def prune_recycle_bin(
    recycle_bin_path: str,
    retention_days: int,
    *,
    now: dt.datetime | None = None,
) -> int:
    """Permanently remove recycle-bin entries older than the retention window."""
    if not recycle_bin_path:
        return 0
    removed = fileops.prune_recycle_bin(recycle_bin_path, retention_days, now=now)
    if removed:
        logger.info("recycle: pruned %d aged recycle-bin entr(y/ies)", removed)
    return removed


__all__ = ["prune_recycle_bin", "sweep_quarantine_to_recycle"]
