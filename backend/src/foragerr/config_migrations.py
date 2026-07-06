"""Versioned config-file migration: stamp, forward-only steps, backup, refuse-newer.

Implements FRG-DEP-004, mechanically parallel to :mod:`foragerr.db.migrations`
but with its own artifact and version counter (``config_schema_version``). The
config file carries a schema-version stamp; on startup :func:`migrate_config`
reads the stamped version and, when it is older than this build supports, steps a
registry of migrators forward one version at a time, backing the original file up
to ``backups/pre-config-migration-<ver>-<ts>/`` (with retention pruning) before
rewriting it. A file stamped *newer* than the build refuses startup with the
config left byte-for-byte untouched — the exact posture
:class:`foragerr.db.migrations.SchemaVersionError` takes for the database.

Kept import-free of :mod:`foragerr.config` (which imports *this* module) so there
is no cycle; the runner works on the raw YAML mapping and the caller validates it.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("foragerr.config_migrations")

#: The config-file schema version this build writes and understands. Bump it and
#: register a migrator in ``_MIGRATORS`` whenever a config-shape change lands.
CURRENT_CONFIG_VERSION = 1

#: The key the version stamp is stored under in ``config.yaml``.
CONFIG_VERSION_KEY = "config_schema_version"

#: Default number of pre-config-migration backups retained under ``backups/``.
DEFAULT_CONFIG_BACKUP_RETENTION = 3

_BACKUPS_DIRNAME = "backups"


class ConfigMigrationError(RuntimeError):
    """A config migration could not be applied."""


class ConfigSchemaVersionError(ConfigMigrationError):
    """The config file is newer than this build supports (FRG-DEP-004)."""


#: A migrator receives the loaded mapping and the resolved config directory
#: (some steps need it to derive a path default) and returns the next-version
#: mapping. The config dir is passed as *context* so a step never has to guess
#: where persistent state lives.
ConfigMigrator = Callable[[dict[str, Any], Path], dict[str, Any]]

#: Where M1 parked upgrade-replaced files (``<config>/quarantine``). An M1 config
#: never permanently deleted a superseded file — it always quarantined it — so
#: the v1 migration MUST preserve that keep-everything semantic (see below).
_M1_QUARANTINE_DIRNAME = "quarantine"


def _migrate_0_to_1(values: dict[str, Any], config_dir: Path) -> dict[str, Any]:
    """Baseline stamp migration: an unversioned (M1) config becomes v1.

    v1 adds naming/media-management fields whose model defaults are safe for a
    *fresh* install — but there is ONE field whose fresh default silently changes
    behavior for an EXISTING M1 install: ``recycle_bin_path`` defaults to ``""``,
    which means *permanently delete* an upgrade-replaced file. M1 never deleted:
    it always quarantined the superseded file under ``<config>/quarantine``. So
    for an existing config that never set the key, we pin ``recycle_bin_path`` to
    that quarantine directory, preserving M1's keep-everything semantics (an
    operator who later wants hard-delete can clear it). A fresh install has no
    config file to migrate, so it keeps the ``""`` default. All other operator
    values pass through verbatim; the runner stamps the version.
    """
    migrated = dict(values)
    if "recycle_bin_path" not in migrated:
        migrated["recycle_bin_path"] = str(config_dir / _M1_QUARANTINE_DIRNAME)
    return migrated


#: ``{from_version: migrator}`` applied one step at a time up to the current
#: version. A missing stamp is treated as version 0 (the M1 baseline).
_MIGRATORS: dict[int, ConfigMigrator] = {
    0: _migrate_0_to_1,
}


def stamped_version(values: dict[str, Any]) -> int:
    """The schema version stamped in a loaded config mapping (missing ⇒ 0)."""
    raw = values.get(CONFIG_VERSION_KEY, 0)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def migrate_forward(
    values: dict[str, Any], from_version: int, config_dir: Path
) -> dict[str, Any]:
    """Apply migrators one step at a time from ``from_version`` to current."""
    result = dict(values)
    version = from_version
    while version < CURRENT_CONFIG_VERSION:
        migrator = _MIGRATORS.get(version)
        if migrator is None:
            raise ConfigMigrationError(
                f"no config migrator registered from schema version {version}"
            )
        result = migrator(result, config_dir)
        version += 1
    return result


def migrate_config(
    config_file: Path,
    values: dict[str, Any],
    config_dir: Path,
    *,
    retention: int = DEFAULT_CONFIG_BACKUP_RETENTION,
    render: Callable[[dict[str, Any]], str] | None = None,
) -> dict[str, Any]:
    """Migrate ``values`` (the loaded ``config.yaml``) forward to current (FRG-DEP-004).

    Refuses (leaving the file untouched, taking no backup) when the stamp is newer
    than this build. When it is older, backs the original file up with retention
    pruning, applies the stepped migrators, stamps the current version, and
    rewrites the file. ``render`` turns the migrated mapping into the file text
    (the caller passes the documented-config renderer so comments regenerate on
    every write); it defaults to a bare YAML dump for standalone use. The rewrite
    is atomic (temp-file + ``fsync`` + ``os.replace``). Returns the (possibly
    migrated) mapping for validation.
    """
    version = stamped_version(values)
    if version == CURRENT_CONFIG_VERSION:
        return values
    if version > CURRENT_CONFIG_VERSION:
        raise ConfigSchemaVersionError(
            f"{CONFIG_VERSION_KEY}: config file {config_file} is stamped at schema "
            f"version {version}, which this build does not understand — it is newer "
            f"than the supported version {CURRENT_CONFIG_VERSION}. Refusing to start; "
            "run a matching or newer application version, or restore the "
            "pre-config-migration backup taken by the newer version."
        )

    # Older: back the original up BEFORE rewriting, then step forward and stamp.
    backup_before_config_migration(config_file, config_dir, version, retention)
    migrated = migrate_forward(values, version, config_dir)
    migrated[CONFIG_VERSION_KEY] = CURRENT_CONFIG_VERSION
    _write_config(config_file, migrated, render)
    logger.info(
        "config: migrated %s from schema version %s to %s",
        config_file,
        version,
        CURRENT_CONFIG_VERSION,
    )
    return migrated


def backup_before_config_migration(
    config_file: Path, config_dir: Path, version: int, retention: int
) -> Path:
    """Copy the pre-migration config into ``backups/`` + prune (FRG-DEP-004)."""
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M%S%f")
    backups_root = config_dir / _BACKUPS_DIRNAME
    target_dir = backups_root / f"pre-config-migration-{version}-{timestamp}"
    target_dir.mkdir(parents=True)
    shutil.copy2(config_file, target_dir / config_file.name)
    prune_config_backups(backups_root, retention)
    logger.info("config: pre-migration backup written to %s", target_dir)
    return target_dir


def prune_config_backups(backups_root: Path, retention: int) -> list[Path]:
    """Keep the newest ``retention`` pre-config-migration backups; prune the rest."""
    if retention < 1:
        retention = 1
    backups = sorted(
        (d for d in backups_root.glob("pre-config-migration-*") if d.is_dir()),
        key=lambda d: d.stat().st_mtime,
    )
    pruned = backups[: max(0, len(backups) - retention)]
    for stale in pruned:
        shutil.rmtree(stale)
        logger.info("config: pruned pre-config-migration backup %s", stale)
    return pruned


def _write_config(
    config_file: Path,
    values: dict[str, Any],
    render: Callable[[dict[str, Any]], str] | None,
) -> None:
    """Atomically rewrite ``config.yaml`` with the migrated values.

    ``render`` (the documented-config renderer when the caller supplies it)
    controls the on-disk form so comments regenerate on every write; without one
    a bare YAML dump is used. The write is atomic so an interrupted rewrite can
    never leave a torn/half-written config in place (the backup also keeps the
    original)."""
    text = render(values) if render is not None else yaml.safe_dump(values, sort_keys=False)
    atomic_write_text(config_file, text)


def atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically: temp file in the same directory,
    ``fsync``, then ``os.replace`` (FRG-DEP-004 / FRG-API-013).

    A reader (or a crash) never observes a partially written config: the final
    path is either the old file or the complete new one. Kept here — dependency
    free — so both the migration runner and the config-resource ``PUT`` handler
    share one writer.
    """
    path = Path(path)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


__all__ = [
    "CONFIG_VERSION_KEY",
    "CURRENT_CONFIG_VERSION",
    "DEFAULT_CONFIG_BACKUP_RETENTION",
    "ConfigMigrationError",
    "ConfigSchemaVersionError",
    "atomic_write_text",
    "backup_before_config_migration",
    "migrate_config",
    "migrate_forward",
    "prune_config_backups",
    "stamped_version",
]
