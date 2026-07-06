"""Consistent database backup primitives (FRG-DB-009 / FRG-DB-003).

The one place that turns a live WAL database into a restorable copy:
:func:`write_consistent_backup` WAL-checkpoints then uses the SQLite backup API
(never a raw file copy, which could capture a torn page set). Both the
pre-migration path (``db/migrations.py``) and the scheduled-backup task
(``db/backup_command.py``) use it, so there is exactly one backup primitive.

Backups live under ``<config>/backups/`` in two independently-retained pools
distinguished by directory-name prefix:

- ``pre-migration-<rev>-<ts>/`` — written before a schema upgrade (FRG-DB-003),
  retained by ``db_backup_retention``.
- ``scheduled-<ts>/`` — the periodic DB+config backup (FRG-DB-009), retained by
  ``db_scheduled_backup_retention``.

:func:`prune_backup_pool` is prefix-scoped so pruning one pool can never delete
a backup from the other. Everything here is synchronous ``sqlite3``/``shutil``;
async callers offload it to a thread.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
from pathlib import Path

from foragerr.db.base import utcnow

logger = logging.getLogger("foragerr.db.backup")

#: Directory under the config dir that holds every backup pool.
BACKUPS_DIRNAME = "backups"

#: Name prefixes for the two independently-retained pools.
PRE_MIGRATION_PREFIX = "pre-migration-"
SCHEDULED_PREFIX = "scheduled-"


def _timestamp() -> str:
    return utcnow().strftime("%Y%m%d%H%M%S%f")


def write_consistent_backup(db_path: Path, dest_dir: Path) -> Path:
    """WAL-checkpoint ``db_path`` then copy it into ``dest_dir`` consistently.

    Uses ``PRAGMA wal_checkpoint(TRUNCATE)`` followed by
    ``source.backup(destination)`` (the SQLite online-backup API) so the copy is
    internally consistent and reflects everything committed before this call —
    never a plain file copy of a live WAL database. Returns the path of the
    written database file (``dest_dir/<db-filename>``). ``dest_dir`` must already
    exist.
    """
    dest_db = dest_dir / db_path.name
    source = sqlite3.connect(db_path)
    try:
        # Bound the wait if a concurrent writer holds the file (the scheduled
        # backup runs while the async engine is open); never block unbounded.
        source.execute("PRAGMA busy_timeout=5000")
        source.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        destination = sqlite3.connect(dest_db)
        try:
            with destination:
                source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()
    return dest_db


def prune_backup_pool(backups_root: Path, prefix: str, retention: int) -> list[Path]:
    """Keep the newest ``retention`` backups whose name starts with ``prefix``.

    Prunes ONLY directories matching ``{prefix}*`` (mtime-sorted, oldest first),
    so the pre-migration and scheduled pools retain independently — pruning one
    never touches the other. A ``retention`` below 1 is floored to 1 to guard a
    direct caller from wiping an entire pool.
    """
    if retention < 1:
        retention = 1
    if not backups_root.exists():
        return []
    backups = sorted(
        (d for d in backups_root.glob(f"{prefix}*") if d.is_dir()),
        key=lambda d: d.stat().st_mtime,
    )
    pruned = backups[: max(0, len(backups) - retention)]
    for stale in pruned:
        shutil.rmtree(stale)
        logger.info("db: pruned backup %s", stale)
    return pruned


def write_scheduled_backup(
    db_path: Path,
    config_path: Path,
    config_dir: Path,
    retention: int,
) -> Path:
    """Write a ``scheduled-<ts>/`` backup of the DB + config file, then prune.

    Creates ``<config>/backups/scheduled-<ts>/`` holding a consistent copy of
    the database (via :func:`write_consistent_backup`) and a copy of the config
    file (``shutil.copy2``, preserving mtime), then prunes the scheduled pool to
    ``retention`` newest. Returns the created directory. The caller is
    responsible for running the pre-backup integrity check first (FRG-DB-012) —
    this function assumes the source is sound.
    """
    backups_root = config_dir / BACKUPS_DIRNAME
    target_dir = backups_root / f"{SCHEDULED_PREFIX}{_timestamp()}"
    target_dir.mkdir(parents=True)

    write_consistent_backup(db_path, target_dir)
    if config_path.exists():
        shutil.copy2(config_path, target_dir / config_path.name)
    else:  # pragma: no cover - config file always present in the running app
        logger.warning("db: scheduled backup: config file %s absent", config_path)

    prune_backup_pool(backups_root, SCHEDULED_PREFIX, retention)
    logger.info("db: scheduled backup written to %s", target_dir)
    return target_dir


def latest_scheduled_backup(config_dir: Path) -> Path | None:
    """The newest ``scheduled-*`` backup directory, or ``None`` if there is none.

    Used by the health surface to compute last-backup age (FRG-NFR-011) — a
    filesystem read, so it survives a restart with no tracking table.
    """
    backups_root = config_dir / BACKUPS_DIRNAME
    if not backups_root.exists():
        return None
    dirs = [d for d in backups_root.glob(f"{SCHEDULED_PREFIX}*") if d.is_dir()]
    if not dirs:
        return None
    return max(dirs, key=lambda d: d.stat().st_mtime)


__all__ = [
    "BACKUPS_DIRNAME",
    "PRE_MIGRATION_PREFIX",
    "SCHEDULED_PREFIX",
    "latest_scheduled_backup",
    "prune_backup_pool",
    "write_consistent_backup",
    "write_scheduled_backup",
]
