"""Versioned config-file migration: stamp, forward steps, backup, refuse-newer
(FRG-DEP-004). Placed alongside ``test_config.py`` (the repo keeps API/config
tests at the top level); the dep-spec's suggested ``tests/config/`` path is the
same coverage under a different folder.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from foragerr.config import CONFIG_FILENAME, ConfigError, load_settings
from foragerr.config_migrations import (
    CONFIG_VERSION_KEY,
    CURRENT_CONFIG_VERSION,
    migrate_config,
    prune_config_backups,
)


def _write_config(config_dir: Path, values: dict) -> Path:
    path = config_dir / CONFIG_FILENAME
    path.write_text(yaml.safe_dump(values, sort_keys=False), encoding="utf-8")
    return path


@pytest.mark.req("FRG-DEP-004")
def test_version_stamp_present_from_first_write(config_dir):
    load_settings()  # generates the default config.yaml
    parsed = yaml.safe_load((config_dir / CONFIG_FILENAME).read_text(encoding="utf-8"))
    assert parsed[CONFIG_VERSION_KEY] == CURRENT_CONFIG_VERSION


@pytest.mark.req("FRG-DEP-004")
def test_forward_stepped_migration_with_retained_backup(config_dir):
    # A config stamped one version behind the build (0 = the M1 baseline).
    _write_config(config_dir, {"log_level": "INFO", CONFIG_VERSION_KEY: 0})

    settings = load_settings()

    # Rewritten stamped at the current version.
    parsed = yaml.safe_load((config_dir / CONFIG_FILENAME).read_text(encoding="utf-8"))
    assert parsed[CONFIG_VERSION_KEY] == CURRENT_CONFIG_VERSION
    assert settings.config_schema_version == CURRENT_CONFIG_VERSION
    # A pre-config-migration backup of the original was retained.
    backups = list((config_dir / "backups").glob("pre-config-migration-0-*"))
    assert len(backups) == 1
    backed_up = yaml.safe_load((backups[0] / CONFIG_FILENAME).read_text(encoding="utf-8"))
    assert backed_up.get(CONFIG_VERSION_KEY, 0) == 0  # the original stamp


@pytest.mark.req("FRG-DEP-004")
def test_user_set_values_survive_migration(config_dir):
    _write_config(config_dir, {"log_level": "WARNING", CONFIG_VERSION_KEY: 0})
    settings = load_settings()
    assert settings.log_level == "WARNING"  # operator value preserved verbatim
    parsed = yaml.safe_load((config_dir / CONFIG_FILENAME).read_text(encoding="utf-8"))
    assert parsed["log_level"] == "WARNING"


@pytest.mark.req("FRG-DEP-004")
def test_newer_than_supported_config_refuses_startup_untouched(config_dir):
    original = _write_config(
        config_dir, {"log_level": "INFO", CONFIG_VERSION_KEY: CURRENT_CONFIG_VERSION + 5}
    )
    before = original.read_bytes()

    with pytest.raises(ConfigError) as excinfo:
        load_settings()

    assert CONFIG_VERSION_KEY in str(excinfo.value)
    assert original.read_bytes() == before  # byte-for-byte untouched
    assert not (config_dir / "backups").exists()  # no backup taken, no rewrite


@pytest.mark.req("FRG-DEP-004")
def test_backup_retention_pruning(tmp_path):
    config_dir = tmp_path / "cfg"
    backups_root = config_dir / "backups"
    backups_root.mkdir(parents=True)
    # More than the retention count of existing backups, oldest→newest by mtime.
    made = []
    for i in range(5):
        d = backups_root / f"pre-config-migration-0-2020010100000{i}"
        d.mkdir()
        (d / CONFIG_FILENAME).write_text("old\n", encoding="utf-8")
        made.append(d)

    pruned = prune_config_backups(backups_root, retention=3)

    remaining = sorted(p.name for p in backups_root.glob("pre-config-migration-*"))
    assert len(remaining) == 3  # kept the newest three
    assert made[-1].name in remaining and made[0].name not in remaining
    assert {p.name for p in pruned} == {made[0].name, made[1].name}


@pytest.mark.req("FRG-DEP-004")
@pytest.mark.req("FRG-PP-013")
def test_m1_config_migration_preserves_keep_everything_recycle_semantics(config_dir):
    """An existing M1 (unversioned) config never permanently deleted a superseded
    file — it quarantined it. Migrating it to v1 must NOT silently adopt the fresh
    ``recycle_bin_path=""`` (permanent-delete) default: it pins the bin at the M1
    quarantine dir so keep-everything semantics survive the upgrade (data loss)."""
    _write_config(config_dir, {"log_level": "INFO"})  # no version stamp ⇒ v0

    settings = load_settings()

    expected = str(config_dir / "quarantine")
    assert settings.recycle_bin_path == expected  # never flipped to hard-delete
    parsed = yaml.safe_load((config_dir / CONFIG_FILENAME).read_text(encoding="utf-8"))
    assert parsed["recycle_bin_path"] == expected


@pytest.mark.req("FRG-DEP-004")
@pytest.mark.req("FRG-PP-013")
def test_fresh_install_keeps_empty_recycle_bin_default(config_dir):
    """A fresh install has no config file to migrate, so the generated config keeps
    the ``""`` (permanent-delete) default — the migration pin is for upgrades only."""
    settings = load_settings()  # generates a first-run documented config

    assert settings.recycle_bin_path == ""
    parsed = yaml.safe_load((config_dir / CONFIG_FILENAME).read_text(encoding="utf-8"))
    assert parsed["recycle_bin_path"] == ""


@pytest.mark.req("FRG-DEP-004")
def test_migrate_config_is_a_noop_at_current_version(tmp_path):
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    values = {"log_level": "INFO", CONFIG_VERSION_KEY: CURRENT_CONFIG_VERSION}
    path = _write_config(config_dir, values)
    before = path.read_bytes()

    result = migrate_config(path, values, config_dir)

    assert result == values
    assert path.read_bytes() == before  # already current → untouched
    assert not (config_dir / "backups").exists()  # no backup at current version
