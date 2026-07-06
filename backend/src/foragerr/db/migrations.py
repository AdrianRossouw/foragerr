"""Startup migration runner: guard, backup, forward-only upgrade.

Implements FRG-DB-002 (versioned forward-only migrations applied at startup,
one at a time, failing revision named, failed revision never stamped),
FRG-DB-003 (pre-migration WAL-checkpointed backup with retention pruning,
only when migrations are pending), and FRG-DB-004 (refuse to start when the
database revision is unknown/newer than the code head — DB left untouched,
no backup taken).

Everything here is synchronous (sqlite3 + Alembic); the startup hook runs it
via ``asyncio.to_thread``.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import Script, ScriptDirectory

from foragerr.db.backup import (
    BACKUPS_DIRNAME,
    PRE_MIGRATION_PREFIX,
    prune_backup_pool,
    write_consistent_backup,
)
from foragerr.db.base import utcnow
from foragerr.db.engine import DB_FILENAME

logger = logging.getLogger("foragerr.db.migrations")

ALEMBIC_DIR = Path(__file__).resolve().parent / "alembic"


class MigrationError(RuntimeError):
    """A migration failed to apply; the failing revision is named."""


class SchemaVersionError(MigrationError):
    """The database schema is newer than (or unknown to) this build (FRG-DB-004)."""


def app_version() -> str:
    """Installed application version (best effort, for error messages)."""
    try:
        from importlib.metadata import version

        return version("foragerr")
    except Exception:  # pragma: no cover - metadata always present under uv
        return "0+unknown"


@dataclass
class PrepareResult:
    """What ``prepare_database`` did at startup."""

    previous_revision: str | None
    head_revision: str | None
    applied: list[str] = field(default_factory=list)
    backup_dir: Path | None = None


def _make_config(db_path: Path, script_location: Path) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(script_location))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return cfg


def current_revision(db_path: Path) -> str | None:
    """The revision stamped in the DB file, or None for fresh/unversioned."""
    if not db_path.exists():
        return None
    # Read-only URI: inspecting the revision must never mutate the file
    # (FRG-DB-004 "refusal leaves the database untouched").
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='alembic_version'"
        ).fetchone()
        if table is None:
            return None
        row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _pending_revisions(
    script: ScriptDirectory, current: str | None, db_path: Path
) -> list[Script]:
    """Revisions to apply, base→head order; refuse unknown/newer (FRG-DB-004)."""
    revisions = list(script.walk_revisions("base", "heads"))
    revisions.reverse()  # walk_revisions yields head→base
    known = {rev.revision for rev in revisions}
    if current is not None and current not in known:
        head = script.get_current_head()
        raise SchemaVersionError(
            f"database {db_path} is stamped at schema revision {current!r}, "
            f"which this application (version {app_version()}, migration head "
            f"{head!r}) does not know — it is newer than this build supports. "
            "Refusing to start; run a matching or newer application version, "
            "or restore the pre-migration backup taken by the newer version."
        )
    if current is None:
        return revisions
    index = next(i for i, rev in enumerate(revisions) if rev.revision == current)
    return revisions[index + 1 :]


def backup_before_migration(
    db_path: Path, config_dir: Path, version: str, retention: int
) -> Path:
    """WAL-checkpointed consistent copy + retention pruning (FRG-DB-003).

    Reuses the shared ``write_consistent_backup`` primitive (SQLite backup API
    after a WAL checkpoint) and the prefix-scoped ``prune_backup_pool`` — the
    same building blocks the scheduled backup (FRG-DB-009) uses, with the
    distinct ``pre-migration-`` prefix so the two pools retain independently.
    """
    timestamp = utcnow().strftime("%Y%m%d%H%M%S%f")
    backups_root = config_dir / BACKUPS_DIRNAME
    target_dir = backups_root / f"{PRE_MIGRATION_PREFIX}{version}-{timestamp}"
    target_dir.mkdir(parents=True)

    write_consistent_backup(db_path, target_dir)

    prune_backups(backups_root, retention)
    logger.info("db: pre-migration backup written to %s", target_dir)
    return target_dir


def prune_backups(backups_root: Path, retention: int) -> list[Path]:
    """Keep the newest ``retention`` pre-migration backups; prune the rest.

    Thin wrapper over the shared, prefix-scoped ``prune_backup_pool`` for the
    ``pre-migration-`` pool (FRG-DB-003); the scheduled pool is pruned by the
    same primitive under its own prefix.
    """
    return prune_backup_pool(backups_root, PRE_MIGRATION_PREFIX, retention)


def prepare_database(
    config_dir: Path,
    *,
    retention: int = 3,
    script_location: Path = ALEMBIC_DIR,
    db_path: Path | None = None,
) -> PrepareResult:
    """The full startup sequence: guard → backup → upgrade (design decision 3).

    Raises :class:`SchemaVersionError` (DB untouched, no backup) when the DB
    revision is unknown/newer, and :class:`MigrationError` naming the failing
    revision when an upgrade script raises (that revision is never stamped —
    each revision applies in its own transaction).
    """
    if db_path is None:
        db_path = config_dir / DB_FILENAME
    cfg = _make_config(db_path, script_location)
    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()
    current = current_revision(db_path)
    pending = _pending_revisions(script, current, db_path)  # may refuse

    result = PrepareResult(previous_revision=current, head_revision=head)
    if not pending:
        logger.info("db: schema already at head revision %s; no migration", head)
        _ensure_wal(db_path)
        return result

    if db_path.exists():
        result.backup_dir = backup_before_migration(
            db_path, config_dir, current or "base", retention
        )

    for revision in pending:
        try:
            command.upgrade(cfg, revision.revision)
        except Exception as exc:
            raise MigrationError(
                f"migration {revision.revision!r} failed to apply: {exc}. "
                f"The database remains at revision "
                f"{current_revision(db_path)!r}."
            ) from exc
        result.applied.append(revision.revision)
        logger.info("db: applied migration %s", revision.revision)

    _ensure_wal(db_path)
    return result


def _ensure_wal(db_path: Path) -> None:
    """Persist WAL journal mode on the file (FRG-DB-005 pairing).

    Runs only after the revision guard has passed — the refusal path never
    touches the database. The per-connection PRAGMAs in the engine still
    assert WAL on every pooled connection.
    """
    if not db_path.exists():  # pragma: no cover - defensive
        return
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    finally:
        conn.close()
