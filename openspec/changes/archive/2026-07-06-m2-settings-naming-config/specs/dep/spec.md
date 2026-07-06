## MODIFIED Requirements

### Requirement: FRG-DEP-004 — versioned config-file migration

The system SHALL stamp the config file with a schema version and apply stepped migrations on upgrade, backing up the previous config file (with retention) before rewriting it, and preserving unknown-but-valid user values.

- **Milestone**: M2
- **Source**: mylar-feature-surface.md §7 ("versioned stepped config migrations (v6→v14/15)"; "automatic config backup before upgrade with retention").
- **Notes**: `config_migrations.py` (new), mechanically parallel to `db/migrations.py` — a separate artifact and version counter (`config_schema_version`). Reuses the DB's backup+prune shape (`backups/pre-config-migration-<ver>-<ts>/`, `config_backup_retention` default 3) and its refuse-newer posture (`SchemaVersionError` analogue). Stamped into every written `config.yaml` from the first generated file (design decision 9). Tag test: `tests/config/test_config_migrations.py`.

#### Scenario: Version stamp present from first write

- **GIVEN** no existing `config.yaml`
- **WHEN** startup generates the default config
- **THEN** the written file carries `config_schema_version` set to the current supported version.

#### Scenario: Forward stepped migration with retained backup

- **GIVEN** a `config.yaml` stamped one schema version behind the build
- **WHEN** the newer build starts
- **THEN** the registered migrator(s) run one step at a time up to the current version, the file is rewritten stamped at the current version, and a `pre-config-migration-*` backup of the original is retained under `backups/`.

#### Scenario: User-set values survive migration

- **GIVEN** an older config with an operator-set value for a field that remains valid
- **WHEN** migration runs
- **THEN** that value is preserved verbatim in the migrated file.

#### Scenario: Newer-than-supported config refuses startup, untouched

- **GIVEN** a `config.yaml` stamped at a version newer than the build supports
- **WHEN** startup runs
- **THEN** it refuses to start with a field-precise error, and the config file is left byte-for-byte untouched with no backup taken and no rewrite (mirroring the DB `SchemaVersionError` refusal).

#### Scenario: Backup retention pruning

- **GIVEN** more than `config_backup_retention` `pre-config-migration-*` backups present
- **WHEN** a migration writes a new backup
- **THEN** the oldest backups beyond the retention count are pruned, keeping the newest `config_backup_retention`.
