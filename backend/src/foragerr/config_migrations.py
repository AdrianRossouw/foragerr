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
import shutil
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


ConfigMigrator = Callable[[dict[str, Any]], dict[str, Any]]


def _migrate_0_to_1(values: dict[str, Any]) -> dict[str, Any]:
    """Baseline stamp migration: an unversioned (M1) config becomes v1.

    v1 only *adds* naming/media-management fields, every one of which supplies a
    safe default through the ``Settings`` model, so no value needs rewriting here
    — operator-set values pass through verbatim. The runner stamps the version.
    """
    return dict(values)


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


def migrate_forward(values: dict[str, Any], from_version: int) -> dict[str, Any]:
    """Apply migrators one step at a time from ``from_version`` to current."""
    result = dict(values)
    version = from_version
    while version < CURRENT_CONFIG_VERSION:
        migrator = _MIGRATORS.get(version)
        if migrator is None:
            raise ConfigMigrationError(
                f"no config migrator registered from schema version {version}"
            )
        result = migrator(result)
        version += 1
    return result


def migrate_config(
    config_file: Path,
    values: dict[str, Any],
    config_dir: Path,
    *,
    retention: int = DEFAULT_CONFIG_BACKUP_RETENTION,
) -> dict[str, Any]:
    """Migrate ``values`` (the loaded ``config.yaml``) forward to current (FRG-DEP-004).

    Refuses (leaving the file untouched, taking no backup) when the stamp is newer
    than this build. When it is older, backs the original file up with retention
    pruning, applies the stepped migrators, stamps the current version, and
    rewrites the file. Returns the (possibly migrated) mapping for validation.
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
    migrated = migrate_forward(values, version)
    migrated[CONFIG_VERSION_KEY] = CURRENT_CONFIG_VERSION
    _write_config(config_file, migrated)
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


def _write_config(config_file: Path, values: dict[str, Any]) -> None:
    """Rewrite ``config.yaml`` with the migrated values (the backup keeps the
    original, comments and all)."""
    config_file.write_text(
        yaml.safe_dump(values, sort_keys=False), encoding="utf-8"
    )


__all__ = [
    "CONFIG_VERSION_KEY",
    "CURRENT_CONFIG_VERSION",
    "DEFAULT_CONFIG_BACKUP_RETENTION",
    "ConfigMigrationError",
    "ConfigSchemaVersionError",
    "backup_before_config_migration",
    "migrate_config",
    "migrate_forward",
    "prune_config_backups",
    "stamped_version",
]
