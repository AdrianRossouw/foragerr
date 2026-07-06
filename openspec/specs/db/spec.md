# DB — Persistence Specification

## Purpose

Baseline requirements for persistence, mined from the
Phase 1 reference research (`docs/research/`). Baseline depth per the Phase 2 scope
decision: SHALL + coarse acceptance; scenario-level elaboration happens in the
milestone change that implements each requirement (FRG-PROC-003, FRG-PROC-009).
## Requirements
### Requirement: FRG-DB-001 — single SQLite database under /config

The system SHALL persist all application state (library, issues, files, queues, job history, provider state, download history) in a single SQLite database file located under the container's `/config` volume.

- **Milestone**: M1
- **Source**: mylar-feature-surface.md §8 "DB" (mylar.db, ~24 tables); sonarr-architecture.md §6 (commands/scheduled_tasks tables).
- **Notes**: Pairs with DEP `/config`-volume requirement — DEP owns the volume convention, DB owns "all state lives in the DB file". Cover-art cache may live beside the DB under `/config` but is reconstructable, not state.

#### Scenario: State survives container recreate with the same volume

- **WHEN** the application has written library and queue state, the container is destroyed, and a new container starts with the same `/config` volume
- **THEN** all previously persisted library and queue state is intact and served identically to before the recreate

#### Scenario: All state lives in the single database file

- **WHEN** the filesystem inside and outside `/config` is inspected after normal operation (series added, jobs run, downloads recorded)
- **THEN** exactly one SQLite database file (plus its WAL/SHM companions) exists, located under `/config`, and no application state files exist outside `/config`

#### Scenario: Fresh start creates the database under /config

- **WHEN** the application starts against an empty `/config` volume
- **THEN** it creates the SQLite database file at its configured path under `/config` and becomes healthy without manual database setup

### Requirement: FRG-DB-002 — versioned schema migrations

The system SHALL manage the database schema with versioned, ordered, forward-only migrations (alembic-style) applied automatically at startup, recording the applied revision in the database.

- **Milestone**: M1
- **Source**: mylar-feature-surface.md §8 DB ("additive idempotent ALTER-TABLE migrations, DB version row"); sonarr-architecture.md §6 (persisted stores imply schema evolution).
- **Notes**: Deliberate divergence from Mylar's ad-hoc idempotent ALTERs — explicit revision chain with up() scripts, testable in CI. Downgrade scripts are NOT required (see refuse-downgrade requirement below).

#### Scenario: Pending migrations apply exactly once at startup

- **WHEN** a build containing newer migrations starts against a database stamped at an older revision
- **THEN** all pending Alembic migrations are applied programmatically during startup, in order, exactly once, and the database's recorded revision equals the application's head revision

#### Scenario: Restart at head is a no-op

- **WHEN** the application restarts against a database already stamped at the head revision
- **THEN** startup completes without applying any migration and the recorded revision is unchanged

#### Scenario: Empty database is migrated from base to head

- **WHEN** the application starts against a brand-new, empty database file
- **THEN** the full forward-only migration chain runs from base to head and the resulting schema matches the head revision

#### Scenario: Failed migration does not stamp the new revision

- **WHEN** a migration script raises an error partway through startup
- **THEN** the application fails to start with an error identifying the failing revision, and the database's recorded revision remains the last successfully applied one

### Requirement: FRG-DB-003 — pre-migration automatic backup

The system SHALL take an automatic backup of the database file before applying any schema migration, retaining at least the most recent N (configurable, default 3) pre-migration backups.

- **Milestone**: M1
- **Source**: mylar-feature-surface.md §7 ("automatic config backup before upgrade with retention") and §8 Maintenance & ops (rolling versioned backups of DB+config).
- **Notes**: Distinct from the scheduled backup requirement below (that one is periodic; this one is event-triggered). Config-file migration backup is a DEP requirement — dedup on wording.

#### Scenario: Backup is taken before migrations run

- **WHEN** startup detects pending migrations against an existing database
- **THEN** before the first migration executes, a WAL-checkpointed copy of the database is written to `/config/backups/pre-migration-<version>-<timestamp>/`, and that copy reflects the pre-migration schema revision

#### Scenario: No backup when there is nothing to migrate

- **WHEN** the application starts against a database already at the head revision
- **THEN** no new pre-migration backup directory is created

#### Scenario: Retention prunes oldest backups beyond the limit

- **WHEN** more pre-migration backups exist than the configured retention count (default 3) after a new backup is taken
- **THEN** the oldest backups are pruned so that exactly the retention count remain, and the most recent backups are the ones kept

#### Scenario: Backup is a consistent, restorable copy

- **WHEN** a pre-migration backup directory is taken while the database has uncheckpointed WAL content
- **THEN** the backed-up database file passes `PRAGMA integrity_check` and contains all data committed before the backup point

### Requirement: FRG-DB-004 — refuse to run against a newer schema

The system SHALL refuse to start (with a clear error naming the schema revision and the application version) when the database schema revision is newer than the running application supports.

- **Milestone**: M1
- **Source**: mylar-feature-surface.md §8 DB (DB version row); divergence — Mylar has no downgrade guard.
- **Notes**: This is the accepted alternative to writing downgrade migrations. Container rollback story: restore the pre-migration backup instead.

#### Scenario: Older build refuses to start against a newer database

- **WHEN** an application build whose migration head is older than the database's recorded revision starts against that database
- **THEN** startup aborts with a non-zero exit before serving any requests, and the error message names both the database's schema revision and the running application version

#### Scenario: Refusal leaves the database untouched

- **WHEN** startup is refused because the database revision is newer than the code supports
- **THEN** the database file's content and recorded revision are byte-for-byte unchanged, and no pre-migration backup is created

#### Scenario: Unknown revision is treated as newer

- **WHEN** the database's recorded revision does not exist in the application's migration chain
- **THEN** the application refuses to start with the same clear error rather than attempting to migrate or run

### Requirement: FRG-DB-005 — WAL journal mode with busy timeout

The system SHALL open the SQLite database in WAL journal mode with `synchronous=NORMAL` (or stricter), foreign keys enabled, and a configured busy timeout on every connection.

- **Milestone**: M1
- **Source**: mylar-feature-surface.md §8 DB ("retry-on-locked wrapper") — WAL is the modern fix for the lock contention Mylar works around; sonarr-architecture.md (SQLite/FastAPI/asyncio target).
- **Notes**: WAL means readers never block on the writer; combined with the single-writer requirement this replaces Mylar's retry-on-locked wrapper almost entirely.

#### Scenario: Every pooled connection reports the required PRAGMAs

- **WHEN** any connection obtained from the engine (including newly created pool connections) is queried for its PRAGMA state
- **THEN** `PRAGMA journal_mode` returns `wal`, `PRAGMA foreign_keys` returns `1`, `PRAGMA synchronous` returns `NORMAL` (1) or stricter, and `PRAGMA busy_timeout` returns the configured non-zero value

#### Scenario: Readers are not blocked by an open write transaction

- **WHEN** a read query executes while a separate write transaction is open and uncommitted
- **THEN** the read completes successfully with the last-committed data, without waiting for the writer or raising a locked error

#### Scenario: Foreign key constraints are enforced

- **WHEN** an insert or delete that violates a declared foreign key constraint is attempted through the persistence layer
- **THEN** the operation fails with a constraint error rather than silently persisting an orphaned or dangling row

### Requirement: FRG-DB-006 — single-writer discipline

The system SHALL serialize all database writes through a single writer path (one writer connection or an async write lock), with any residual `SQLITE_BUSY`/locked errors retried with bounded backoff rather than surfaced to callers.

- **Milestone**: M1
- **Source**: mylar-feature-surface.md §8 ("plus a serialized DB-writer thread"; DB "locked-retry wrapper").
- **Notes**: In asyncio this is naturally a single writer session/queue; keep read connections separate and read-only. This is the DB-side twin of SCHED's worker-pool design.

#### Scenario: Concurrent writers are serialized without locked errors

- **WHEN** a stress test runs many concurrent tasks that each perform mutations through `write_session()` (simulating search, post-processing, and scheduler activity)
- **THEN** all mutations complete successfully with zero unhandled "database is locked" errors surfaced to callers, and the final row counts match the total work submitted

#### Scenario: Writes hold the lock one at a time

- **WHEN** two tasks enter `write_session()` concurrently
- **THEN** the second task's session does not begin its write transaction until the first has committed or rolled back, observable as non-overlapping write windows

#### Scenario: Residual locked errors are retried, not surfaced

- **WHEN** a write encounters a residual `SQLITE_BUSY`/locked condition (e.g., induced by an external process holding the lock briefly)
- **THEN** the write is retried with bounded backoff and either eventually succeeds or fails with a distinct timeout error after the bound is exhausted — a raw locked error never reaches the caller

### Requirement: FRG-DB-007 — transactional multi-step operations

The system SHALL execute multi-step state changes (e.g., series add with issues, import finalization, queue state transitions, migration steps) as atomic transactions that either fully commit or fully roll back.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §1.2 (add → refresh chain), §4.4-4.5 (state machine transitions); mylar-comicvine.md §3.7 (silent partial writes as an anti-pattern).
- **Notes**: Backs NFR crash-safe-queues. Event publication happens after commit, not inside the transaction.

#### Scenario: Interrupted series add leaves no partial records

- **WHEN** the process is killed (or the operation raises) partway through a series-add that inserts the series row plus its issue rows in one `write_session()`
- **THEN** on next inspection the database contains either the complete series with all its issues or no trace of the series — never a series with a partial issue set

#### Scenario: Failure inside write_session rolls back every statement

- **WHEN** an exception is raised inside a `write_session()` block after some statements have executed
- **THEN** the session rolls back, none of the block's changes are visible to subsequent readers, and the exception propagates to the caller

#### Scenario: Events publish only after commit

- **WHEN** a multi-step operation inside `write_session()` would publish domain events but the transaction fails before commit
- **THEN** no event is published; and when the same operation commits successfully, its events are published only after the commit completes

### Requirement: FRG-DB-008 — typed, sentinel-free schema

The system SHALL store all fields as typed columns with SQL NULL for missing values, and SHALL NOT persist sentinel strings (e.g., `'None'`, `'0000'`, `'0000-00-00'`) in place of nulls; issue numbers SHALL be stored in a form preserving decimals and suffixes (e.g., `1.5`, `1.MU`).

- **Milestone**: M1
- **Source**: mylar-comicvine.md §3.7-3.8 (sentinel-string weaknesses, explicit candidate requirement); sonarr-architecture.md §1.1 (decimal/string issue numbers).
- **Notes**: Explicit divergence from Mylar. Heuristic-derived fields (book type, volume) carry a provenance flag per the ComicVine research — that flag is a schema concern here, behavior is META's.

#### Scenario: Missing values persist and round-trip as SQL NULL

- **WHEN** a record is saved through the persistence layer with an absent optional field (e.g., no publication date, no ComicVine ID)
- **THEN** the corresponding column contains SQL NULL, and reading the record back yields `None` — not `'None'`, `'0000'`, `'0000-00-00'`, or any other sentinel string

#### Scenario: Sentinel strings are rejected by the persistence layer

- **WHEN** a write attempts to persist a sentinel string (`'None'`, `'0000'`, `'0000-00-00'`) into a date, number, or id column
- **THEN** the persistence layer rejects or normalizes the value so that a data-quality query scanning those columns for sentinel strings returns zero rows

#### Scenario: Issue numbers preserve decimals and suffixes

- **WHEN** issues numbered `1`, `1.5`, and `1.MU` are stored and read back
- **THEN** each issue number round-trips exactly as written (stored as TEXT), with no coercion to integers, floats, or lossy normalization

#### Scenario: Typed columns reject mistyped values

- **WHEN** a value of the wrong type is written to a typed column (e.g., a non-date string to a date column) through the persistence layer
- **THEN** the write fails with a validation or type error rather than storing a stringly-typed approximation

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

### Requirement: FRG-DB-011 — library export and import

The system SHALL export the library definition (series, monitored flags, per-series settings, issue statuses — not media files) to a portable JSON document and import such a document into a fresh instance.

- **Milestone**: B
- **Source**: mylar-feature-surface.md §8 Maintenance & ops ("JSON export/import of the library").
- **Notes**: Also the escape hatch for future schema disasters and the Mylar→foragerr migration vehicle (a Mylar-import adapter would build on this format; that adapter itself is backlog).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Export from instance A, import into empty instance B; B shows the same series list with the same monitored flags and settings, and triggers metadata refresh for each.

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

