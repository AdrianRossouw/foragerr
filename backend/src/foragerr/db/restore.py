"""Startup restore-from-marker hook (FRG-DB-010).

There is deliberately **no live-restore endpoint**: a running single-writer
SQLite process holds its file open with WAL side files, so a safe swap can only
happen while the database is closed. This hook runs at startup, BEFORE the
engine opens or migrations run, driven by a ``/config/restore-from`` marker.

On a present marker it:

1. resolves the named backup through the ``security.paths`` confinement so the
   target MUST live under ``<config>/backups`` — a traversal/absolute escape is
   refused, not followed;
2. runs a full ``PRAGMA integrity_check`` on the backup's database and refuses a
   corrupt source;
3. snapshots the current live database (+ WAL side files) and config file aside
   to ``<config>/backups/pre-restore-<ts>/``;
4. swaps the backup's database (and its config file, if present) into place,
   discarding any stale live WAL/SHM so the restored file is authoritative;
5. deletes the marker so a restore never loops.

A refusal (confinement violation or corrupt backup) leaves the live database and
config **byte-for-byte unchanged**, logs the reason, and lets startup proceed
against the untouched live database — it never swaps in a rejected target. All
synchronous; the startup hook offloads it to a thread.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from foragerr.config import CONFIG_FILENAME
from foragerr.db.backup import BACKUPS_DIRNAME, write_consistent_backup
from foragerr.db.base import utcnow
from foragerr.db.engine import DB_FILENAME
from foragerr.db.integrity import run_full_integrity_check
from foragerr.security.paths import PathConfinementError, validate_under_root

logger = logging.getLogger("foragerr.db.restore")

#: The marker file under the config dir that requests a startup restore.
RESTORE_MARKER_NAME = "restore-from"

#: WAL/SHM side files that must be cleared so the restored DB is authoritative.
_WAL_SUFFIXES = ("-wal", "-shm")


@dataclass(frozen=True)
class RestoreResult:
    """What :func:`apply_restore_marker` did (for logging + tests)."""

    status: str  # "restored" | "refused"
    target: Path | None = None
    snapshot_dir: Path | None = None
    reason: str | None = None


def _resolve_target(config_dir: Path, raw: str) -> Path:
    """Resolve the marker's named backup, confined under ``<config>/backups``.

    ``raw`` may be a bare backup directory name, a path relative to the backups
    root, or an absolute path; any form that resolves outside the backups root
    raises :class:`PathConfinementError` and is refused (never followed).
    """
    backups_root = config_dir / BACKUPS_DIRNAME
    raw_path = Path(raw)
    candidate = raw_path if raw_path.is_absolute() else backups_root / raw_path
    # realpath containment: rejects `..` traversal and absolute escapes.
    return validate_under_root(candidate, [backups_root])


def apply_restore_marker(config_dir: Path) -> RestoreResult | None:
    """Honor a ``restore-from`` marker if present (FRG-DB-010).

    Returns ``None`` when there is no marker (the common case). Otherwise returns
    a :class:`RestoreResult` describing the restore or the refusal. Never raises
    for an invalid/corrupt target — a refusal leaves the live files untouched.
    """
    config_dir = Path(config_dir)
    marker = config_dir / RESTORE_MARKER_NAME
    if not marker.exists():
        return None

    raw = marker.read_text(encoding="utf-8").strip()
    if not raw:
        logger.error(
            "db: restore marker %s is empty; leaving the live database untouched",
            marker,
        )
        return RestoreResult(status="refused", reason="empty marker")

    try:
        target = _resolve_target(config_dir, raw)
    except PathConfinementError as exc:
        logger.error(
            "db: restore refused — target %r escapes the backups root (%s); "
            "the live database is left untouched",
            raw,
            exc,
        )
        return RestoreResult(status="refused", reason=str(exc))

    backup_db = target / DB_FILENAME
    if not target.is_dir() or not backup_db.exists():
        logger.error(
            "db: restore refused — backup %s has no %s; live database untouched",
            target,
            DB_FILENAME,
        )
        return RestoreResult(
            status="refused", target=target, reason="backup database missing"
        )

    integrity = run_full_integrity_check(backup_db)
    if not integrity.ok:
        logger.error(
            "db: restore refused — backup %s failed integrity (%s); live "
            "database untouched",
            backup_db,
            integrity.detail,
        )
        return RestoreResult(
            status="refused", target=target, reason=integrity.detail
        )

    # Snapshot the current live DB (+ side files) and config aside FIRST.
    snapshot_dir = config_dir / BACKUPS_DIRNAME / f"pre-restore-{_timestamp()}"
    snapshot_dir.mkdir(parents=True)
    live_db = config_dir / DB_FILENAME
    live_config = config_dir / CONFIG_FILENAME
    if live_db.exists():
        # A consistent snapshot of the CURRENT db, so a botched restore is
        # itself recoverable (checkpoint+backup API, not a torn file copy).
        write_consistent_backup(live_db, snapshot_dir)
    if live_config.exists():
        shutil.copy2(live_config, snapshot_dir / live_config.name)

    # Clear stale WAL/SHM so the restored file is authoritative, then swap.
    for suffix in _WAL_SUFFIXES:
        side = config_dir / f"{DB_FILENAME}{suffix}"
        if side.exists():
            side.unlink()
    shutil.copy2(backup_db, live_db)
    backup_config = target / CONFIG_FILENAME
    if backup_config.exists():
        shutil.copy2(backup_config, live_config)

    marker.unlink()  # never loop a restore
    logger.warning(
        "db: restored database from %s (live snapshot saved to %s); marker cleared",
        target,
        snapshot_dir,
    )
    return RestoreResult(status="restored", target=target, snapshot_dir=snapshot_dir)


def _timestamp() -> str:
    return utcnow().strftime("%Y%m%d%H%M%S%f")


__all__ = [
    "RESTORE_MARKER_NAME",
    "RestoreResult",
    "apply_restore_marker",
]
