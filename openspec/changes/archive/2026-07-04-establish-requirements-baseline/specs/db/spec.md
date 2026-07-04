# db Spec Delta

## ADDED Requirements


### Requirement: FRG-DB-001 — single SQLite database under /config

The system SHALL persist all application state (library, issues, files, queues, job history, provider state, download history) in a single SQLite database file located under the container's `/config` volume.

- **Milestone**: M1
- **Source**: mylar-feature-surface.md §8 "DB" (mylar.db, ~24 tables); sonarr-architecture.md §6 (commands/scheduled_tasks tables).
- **Notes**: Pairs with DEP `/config`-volume requirement — DEP owns the volume convention, DB owns "all state lives in the DB file". Cover-art cache may live beside the DB under `/config` but is reconstructable, not state.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** After a container recreate with the same `/config` volume, all library and queue state is intact; no state exists outside `/config`.

### Requirement: FRG-DB-002 — versioned schema migrations

The system SHALL manage the database schema with versioned, ordered, forward-only migrations (alembic-style) applied automatically at startup, recording the applied revision in the database.

- **Milestone**: M1
- **Source**: mylar-feature-surface.md §8 DB ("additive idempotent ALTER-TABLE migrations, DB version row"); sonarr-architecture.md §6 (persisted stores imply schema evolution).
- **Notes**: Deliberate divergence from Mylar's ad-hoc idempotent ALTERs — explicit revision chain with up() scripts, testable in CI. Downgrade scripts are NOT required (see refuse-downgrade requirement below).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Starting a build with a newer schema against an older database applies pending migrations exactly once and stamps the new revision; restart is a no-op.

### Requirement: FRG-DB-003 — pre-migration automatic backup

The system SHALL take an automatic backup of the database file before applying any schema migration, retaining at least the most recent N (configurable, default 3) pre-migration backups.

- **Milestone**: M1
- **Source**: mylar-feature-surface.md §7 ("automatic config backup before upgrade with retention") and §8 Maintenance & ops (rolling versioned backups of DB+config).
- **Notes**: Distinct from the scheduled backup requirement below (that one is periodic; this one is event-triggered). Config-file migration backup is a DEP requirement — dedup on wording.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** After a startup that ran migrations, a timestamped pre-migration copy exists under `/config`; older copies beyond the retention count are pruned.

### Requirement: FRG-DB-004 — refuse to run against a newer schema

The system SHALL refuse to start (with a clear error naming the schema revision and the application version) when the database schema revision is newer than the running application supports.

- **Milestone**: M1
- **Source**: mylar-feature-surface.md §8 DB (DB version row); divergence — Mylar has no downgrade guard.
- **Notes**: This is the accepted alternative to writing downgrade migrations. Container rollback story: restore the pre-migration backup instead.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Pointing an older build at a migrated database exits non-zero with an actionable error; the database file is not modified.

### Requirement: FRG-DB-005 — WAL journal mode with busy timeout

The system SHALL open the SQLite database in WAL journal mode with `synchronous=NORMAL` (or stricter), foreign keys enabled, and a configured busy timeout on every connection.

- **Milestone**: M1
- **Source**: mylar-feature-surface.md §8 DB ("retry-on-locked wrapper") — WAL is the modern fix for the lock contention Mylar works around; sonarr-architecture.md (SQLite/FastAPI/asyncio target).
- **Notes**: WAL means readers never block on the writer; combined with the single-writer requirement this replaces Mylar's retry-on-locked wrapper almost entirely.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** `PRAGMA journal_mode` returns `wal` at runtime; a reader query succeeds while a write transaction is open; connections report `foreign_keys=1` and a non-zero busy_timeout.

### Requirement: FRG-DB-006 — single-writer discipline

The system SHALL serialize all database writes through a single writer path (one writer connection or an async write lock), with any residual `SQLITE_BUSY`/locked errors retried with bounded backoff rather than surfaced to callers.

- **Milestone**: M1
- **Source**: mylar-feature-surface.md §8 ("plus a serialized DB-writer thread"; DB "locked-retry wrapper").
- **Notes**: In asyncio this is naturally a single writer session/queue; keep read connections separate and read-only. This is the DB-side twin of SCHED's worker-pool design.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A stress test with concurrent search, post-processing, and scheduler activity produces zero unhandled database-locked errors.

### Requirement: FRG-DB-007 — transactional multi-step operations

The system SHALL execute multi-step state changes (e.g., series add with issues, import finalization, queue state transitions, migration steps) as atomic transactions that either fully commit or fully roll back.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §1.2 (add → refresh chain), §4.4-4.5 (state machine transitions); mylar-comicvine.md §3.7 (silent partial writes as an anti-pattern).
- **Notes**: Backs NFR crash-safe-queues. Event publication happens after commit, not inside the transaction.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Killing the process mid-way through a series add leaves either the complete series with all issues or nothing — never a partial record set.

### Requirement: FRG-DB-008 — typed, sentinel-free schema

The system SHALL store all fields as typed columns with SQL NULL for missing values, and SHALL NOT persist sentinel strings (e.g., `'None'`, `'0000'`, `'0000-00-00'`) in place of nulls; issue numbers SHALL be stored in a form preserving decimals and suffixes (e.g., `1.5`, `1.MU`).

- **Milestone**: M1
- **Source**: mylar-comicvine.md §3.7-3.8 (sentinel-string weaknesses, explicit candidate requirement); sonarr-architecture.md §1.1 (decimal/string issue numbers).
- **Notes**: Explicit divergence from Mylar. Heuristic-derived fields (book type, volume) carry a provenance flag per the ComicVine research — that flag is a schema concern here, behavior is META's.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Schema review + a data-quality test asserting no sentinel-string values can be inserted through the persistence layer for date/number/id columns.

### Requirement: FRG-DB-009 — scheduled backups with retention

The system SHALL create periodic backups of the database (and config file) on a configurable schedule, keeping a configurable number of rolling backups under `/config` and pruning older ones.

- **Milestone**: M2
- **Source**: mylar-feature-surface.md §8 Maintenance & ops ("rolling versioned backups of DB+config with retention"); sonarr-architecture.md §6.1 (Backup as a scheduled command).
- **Notes**: Backup of a live WAL database must use the SQLite backup API or `VACUUM INTO`, not a file copy. Runs as a SCHED command so it appears in job history.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** After the backup job runs (scheduled or force-run), a new timestamped backup exists; when the retention count is exceeded the oldest is removed.

### Requirement: FRG-DB-010 — restore from backup

The system SHALL provide a documented, supported restore path from any retained backup that results in a consistent database matching the backup point.

- **Milestone**: M2
- **Source**: mylar-feature-surface.md §8 Maintenance & ops (DB import tool, maintenance mode).
- **Notes**: May be an offline/CLI procedure (stop container, swap file) rather than a UI feature — Mylar's maintenance-mode web UI is deliberately NOT baselined.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Restoring a backup taken before a known change yields a running system without that change and passes integrity check.

### Requirement: FRG-DB-011 — library export and import

The system SHALL export the library definition (series, monitored flags, per-series settings, issue statuses — not media files) to a portable JSON document and import such a document into a fresh instance.

- **Milestone**: B
- **Source**: mylar-feature-surface.md §8 Maintenance & ops ("JSON export/import of the library").
- **Notes**: Also the escape hatch for future schema disasters and the Mylar→foragerr migration vehicle (a Mylar-import adapter would build on this format; that adapter itself is backlog).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Export from instance A, import into empty instance B; B shows the same series list with the same monitored flags and settings, and triggers metadata refresh for each.

### Requirement: FRG-DB-012 — integrity verification

The system SHALL run `PRAGMA integrity_check` (or `quick_check`) at startup and before each scheduled backup, surfacing failures as a health error rather than continuing silently.

- **Milestone**: M2
- **Source**: mylar-feature-surface.md §8 (exception capture, maintenance tooling) — divergence: Mylar has no proactive integrity checking.
- **Notes**: Feeds the DEP health endpoint and NFR observability. quick_check at startup keeps the NFR startup-time target reachable; full check can ride the backup job.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A deliberately corrupted test database causes startup to report an unhealthy status naming the integrity failure.
