# db — delta for m2-ops-health-backups

## MODIFIED Requirements

### Requirement: FRG-DB-009 — scheduled backups with retention

The system SHALL create periodic backups of the database and the config file on a configurable schedule, writing each as a consistent, restorable copy under `/config/backups/scheduled-<timestamp>/` and keeping a configurable rolling number of scheduled backups (pruning the oldest beyond the count). The backup SHALL run as a scheduled SCHED command (so it appears in job history and is force-runnable) and SHALL produce its copy with the SQLite backup API after a WAL checkpoint — never a raw file copy of a live WAL database. The scheduled-backup pool is independent of the pre-migration pool (FRG-DB-003): the two use distinct name prefixes and retain independently.

- **Milestone**: M2
- **Source**: mylar-feature-surface.md §8 Maintenance & ops ("rolling versioned backups of DB+config with retention"); sonarr-architecture.md §6.1 (Backup as a scheduled command).
- **Notes**: Reuses the checkpoint-then-`source.backup(destination)` primitive already proven by `db/migrations.py::backup_before_migration` (extracted to a shared `write_consistent_backup` helper so there is one backup primitive), and prunes via the existing mtime-sorted `prune_backups` semantics scoped to the `scheduled-*` glob. New config: `db_backup_interval_seconds` (default 86400/daily, clamped to a documented minimum) and `db_scheduled_backup_retention` (`ge=1`, default 7). "Back up now" is force-running this task (FRG-SCHED-007) — no separate endpoint. A full integrity check (FRG-DB-012) is the first step of the job; a corrupt database aborts the backup rather than rotating a good copy out for a copy of corruption. Rotation is count-based rolling retention only — age-based pruning is deliberately out of scope. Backups contain provider credentials in plaintext (RISK-041, accepted): they stay under `/config` with no off-box transport.

#### Scenario: Scheduled backup produces a timestamped DB+config copy

- **WHEN** the `backup-database` scheduled task runs (on its interval or force-run)
- **THEN** a new `/config/backups/scheduled-<timestamp>/` directory exists containing a copy of the database file (written via the SQLite backup API after a WAL checkpoint, passing `PRAGMA integrity_check`) and a copy of the config file, and the run is recorded in job history

#### Scenario: Rolling retention prunes the oldest scheduled backups

- **WHEN** more `scheduled-*` backups exist than `db_scheduled_backup_retention` after a new one is written
- **THEN** the oldest scheduled backups are pruned so exactly the retention count remain (newest kept), and no `pre-migration-*` backup is touched

#### Scenario: A corrupt database aborts the backup

- **WHEN** the pre-backup full `PRAGMA integrity_check` fails
- **THEN** no `scheduled-*` backup directory is written (the rolling pool is not rotated), the job fails visibly in job history, and a `database` health error naming the integrity failure is surfaced (FRG-DB-012)

#### Scenario: File copy of a live WAL database is not used

- **WHEN** a backup is taken while the database has uncheckpointed WAL content
- **THEN** the backed-up database file is internally consistent (passes `PRAGMA integrity_check`) and reflects all data committed before the backup point — it is produced by checkpoint + backup API, never a plain file copy that could capture a torn page set

### Requirement: FRG-DB-010 — restore from backup

The system SHALL provide a documented, supported restore path from any retained backup (scheduled or pre-migration) that results in a consistent database matching the backup point. Restore is an offline / startup-time operation — there is deliberately no live-restore endpoint, because a running single-writer SQLite process cannot safely swap the database file it holds open. The supported forms are (a) a documented offline swap of the backup's database and config file over the live ones under `/config` while the container is stopped, and (b) a startup-time restore hook driven by a `/config/restore-from` marker that validates, snapshots-aside, and swaps the named backup in before the database engine opens.

- **Milestone**: M2
- **Source**: mylar-feature-surface.md §8 Maintenance & ops (DB import tool, maintenance mode).
- **Notes**: Mylar's live maintenance-mode web UI is deliberately NOT baselined. The startup marker hook resolves its named backup through the existing `security.paths` confinement so the target MUST live under `/config/backups` (a traversal/absolute escape is refused, not followed), verifies the backup's `integrity_check`, moves the current live DB+config aside to a `pre-restore-<timestamp>/` safety copy, swaps the backup's files in, and deletes the marker so a restore never loops. The System UI lists available backups and shows the procedure; the swap itself always happens at startup.

#### Scenario: Offline swap restores to the backup point

- **WHEN** an admin stops the container, copies a retained backup's database and config file over the live files under `/config`, and restarts
- **THEN** the system starts against the restored database, passes its integrity check, and reflects exactly the state at the backup point (a change made after the backup is absent)

#### Scenario: Startup restore-marker hook validates, snapshots, and swaps

- **WHEN** a `/config/restore-from` marker naming a retained backup is present at startup
- **THEN** before the engine opens, the app resolves the target under `/config/backups`, runs `integrity_check` on the backup, moves the current live database+config aside to a `pre-restore-<timestamp>/` copy, swaps the backup's files into place, deletes the marker, and then boots normally against the restored database

#### Scenario: A hostile or corrupt restore target is refused

- **WHEN** the `/config/restore-from` marker names a path that resolves outside `/config/backups`, or names a backup whose database fails `integrity_check`
- **THEN** the restore is refused (the live database and config are left byte-for-byte unchanged, no swap occurs), the refusal is logged with the reason, and startup either proceeds against the untouched live database or aborts with a clear error — never swaps in the rejected target

#### Scenario: No live-restore endpoint exists

- **WHEN** the running API surface is inspected
- **THEN** there is no endpoint that swaps the live database at runtime — restore is available only via the offline swap or the startup marker hook

### Requirement: FRG-DB-012 — integrity verification

The system SHALL run a SQLite integrity check at startup (`PRAGMA quick_check`) and a full `PRAGMA integrity_check` before every scheduled backup, surfacing any failure as a health error rather than continuing silently or backing up a corrupt database. A startup integrity failure marks the `database` component as an error in the health surface (FRG-NFR-011 / FRG-API-014) and is logged loudly; the pre-backup check gates the backup (FRG-DB-009).

- **Milestone**: M2
- **Source**: mylar-feature-surface.md §8 (exception capture, maintenance tooling) — divergence: Mylar has no proactive integrity checking.
- **Notes**: `quick_check` at startup keeps the startup-time NFR reachable while catching gross corruption; the full check rides the ~daily backup job, off the request path. On a startup failure the app still boots (so the admin can reach the System screen and restore) — the failure is surfaced as a `database` health error, distinct from the DEP root `/health` liveness probe. The health item clears on the next clean check without a restart.

#### Scenario: Startup integrity failure surfaces as a health error

- **WHEN** the application starts against a deliberately corrupted database
- **THEN** the startup `PRAGMA quick_check` failure is logged and the `database` component reports an error state in `GET /api/v1/health` / `GET /api/v1/system/health` naming the integrity failure — the failure is not swallowed

#### Scenario: Pre-backup full check gates the scheduled backup

- **WHEN** the scheduled backup job runs and the full `PRAGMA integrity_check` fails
- **THEN** the backup is aborted (no `scheduled-*` directory is written) and a `database` health error is recorded, so a corrupt database is never rotated into the backup pool (FRG-DB-009)

#### Scenario: A clean check clears the health error without restart

- **WHEN** a previously failing integrity check subsequently passes (e.g. after a restore)
- **THEN** the `database` health error clears on the next check with no restart required
