# Design — m2-ops-health-backups

## Context

Grounding (verified against the current tree at v0.2.5):

- **Backup primitive already exists.** `db/migrations.py::backup_before_migration`
  does the right thing for a live WAL DB: `sqlite3.connect(db_path)` →
  `PRAGMA wal_checkpoint(TRUNCATE)` → `source.backup(destination)` into
  `/config/backups/pre-migration-<version>-<timestamp>/`, then
  `prune_backups(backups_root, retention)` keeps the newest N by mtime.
  `db_backup_retention` (config, `ge=1`, default 3) governs the pre-migration
  pool. This change reuses the checkpoint+backup mechanism and the pruning
  helper, with a **distinct name prefix** for the scheduled pool.
- **Scheduler infrastructure is ready.** `IntervalScheduler` (over the
  `scheduled_tasks` table) exposes `register_task(name, command_name, *,
  interval_seconds, min_interval_seconds)`, `force_run(name)` (FRG-SCHED-007 —
  enqueues now, resets `last_run`, dedups), and `status()` returning
  `[{name, interval_seconds, last_run, next_run}]`. Commands are typed Pydantic
  models registered via `register_command` + `register_handler` with dedup on
  `(name, payload_hash)` and an `exclusivity_group` class var. `HousekeepingCommand`
  is the existing precedent for a periodic tidy-up command.
- **Per-provider health state already persists.** `providers/backoff.py`
  `ProviderBackoff.health(...)` returns every tracked provider's `BackoffStatus`
  (`level`, `remaining_seconds`, `healthy`, disabled-until) from the
  `provider_backoff` table (FRG-NFR-005/IDX-010). This is exactly the
  last-failure/disabled-until state FRG-NFR-011 needs — no new tracking table.
- **`/system/status` and the root `/health` already exist.**
  `api/system.py::system_status` returns `{version, commit, build_date}`
  (FRG-DEP-009/010). `api/health.py` serves the **root, unauthenticated
  `GET /health`** — a DEP liveness/readiness probe returning up/down per
  component (database/workers/scheduler/migrations) for the Docker HEALTHCHECK.
  This is NOT the FRG-API-014 health surface and must stay untouched.
- **Root folders** carry free-space already (surfaced on the Media Management
  settings screen from ch4); the health service reuses that read.

## Goals / Non-Goals

**Goals:** scheduled DB+config backups with rolling retention as a force-runnable
SCHED command; startup + pre-backup integrity checks that surface failure as a
health error; a documented + startup-marker restore path; the system
status/health/task API surface (FRG-API-014) and its per-component health view
(FRG-NFR-011); the System UI area (FRG-UI-016).

**Non-Goals:** encryption-at-rest / secret store (M5, RISK-041); off-box/cloud/
downloadable backups; a live-restore endpoint; library JSON export (DB-011, B);
metrics/telemetry; notifications; a log viewer; age-based pruning; any SCHED/DEP
requirement change.

## Decisions

1. **Scheduled backup is a SCHED command, not a bespoke subsystem.** Register a
   `backup-database` command (`BackupDatabaseCommand`, `exclusivity_group =
   "backup"`) + handler, and a `backup-database` scheduled task via the existing
   `scheduler.register_task` in `app.py` (new config
   `db_backup_interval_seconds`, default 86400 = daily, `min_interval_seconds`
   ~3600). Because it is a SCHED command it lands in job history (FRG-SCHED-008
   territory) and is force-runnable. **"Back up now" == `force_run("backup-
   database")`** through the FRG-SCHED-007 path — no separate "backup" endpoint,
   no parallel trigger mechanism. Rationale: FRG-DB-009's own note says "Runs as
   a SCHED command so it appears in job history"; reusing `force_run` gives us
   the timer reset + dedup for free. Alternative (a dedicated `POST /system/
   backup`) rejected: it would duplicate the scheduler's trigger/dedup/history
   for no gain.

2. **Backup mechanics: SQLite backup API, not file copy; DB + config; distinct
   pool.** The handler: (a) run a full `PRAGMA integrity_check` (decision 4); (b)
   `PRAGMA wal_checkpoint(TRUNCATE)`; (c) `source.backup(destination)` into
   `/config/backups/scheduled-<timestamp>/<db-filename>`; (d) copy the config
   file into the same directory (`shutil.copy2`); (e)
   `prune_backups`-style pruning **restricted to the `scheduled-*` glob** so the
   scheduled pool and the pre-migration pool retain independently. Reuse the
   checkpoint+`source.backup` code from `migrations.py` (extract a small shared
   `write_consistent_backup(db_path, dest_dir)` helper rather than copy it, so
   there is one backup primitive). Rotation = **count-based rolling retention**
   (`db_scheduled_backup_retention`, `ge=1`, default 7) via mtime sort, matching
   the existing `prune_backups` semantics; age-based pruning is a non-goal.
   File copy of a live WAL database is explicitly rejected (FRG-DB-009 note): it
   can capture a torn page set. `VACUUM INTO` is a viable alternative but the
   `source.backup` path is already proven and preserves the pre-migration
   symmetry, so we keep it.

3. **Restore: documented offline swap + a startup-time marker hook; no live
   endpoint.** A running foragerr holds the single-writer connection open
   (FRG-DB-006) with WAL side files; swapping the DB file underneath it is
   unsafe. So restore is inherently a DB-closed operation and belongs at
   startup, before the engine opens. Two supported forms, both documented:
   - **Offline swap** (admin): stop the container, copy the chosen
     `scheduled-*/` (or `pre-migration-*/`) DB + config file over the live ones
     under `/config`, start. Simplest, always available.
   - **Startup restore-marker hook** (first-class, testable): if
     `/config/restore-from` (a file naming a backup directory, or that directory
     itself) is present at startup, the prepare sequence — **before** opening the
     engine or running migrations — (i) resolves the named directory through the
     existing `security.paths` confinement so it MUST live under
     `/config/backups` (a traversal/absolute escape is refused, not followed),
     (ii) runs `integrity_check` on the backup's DB and refuses a corrupt source,
     (iii) moves the current live DB + config aside to a
     `pre-restore-<timestamp>/` safety copy, (iv) swaps the backup's files into
     place, (v) deletes the marker so a restore never loops. Then normal startup
     (guard → migrate → serve) proceeds against the restored file. The UI's
     System screen lists available backups and shows the restore instructions;
     dropping the marker may be an admin convenience but the **swap only ever
     happens at startup**. Justification for no live endpoint: the swap cannot be
     done safely while the process serves; a "restore" button that requires a
     restart is honestly modeled as "prepare a restore, then restart."

4. **Integrity checks (FRG-DB-012): quick at startup, full before backup,
   failure ⇒ health error.** `PRAGMA quick_check` runs at startup (a startup
   hook, off the event loop) — fast enough to keep the startup-time NFR while
   catching gross corruption; a failure marks the `database` component **error**
   in the health surface and is logged loudly (the app still boots so the admin
   can reach the System screen and restore — a hard abort would hide the very UI
   that explains the fix; the DEP root `/health` liveness stays a separate
   concern). The **full** `PRAGMA integrity_check` runs as step (a) of every
   scheduled backup; on failure the backup **aborts** (no `scheduled-*` dir is
   written — we never rotate a good backup out in favor of a copy of corruption)
   and records a persistent `database` health error carrying the failure detail.
   The health item clears on the next clean check.

5. **Two `/health` surfaces, disambiguated.** The existing root `GET /health`
   (DEP, unauthenticated, up/down for the Docker probe) is untouched. FRG-API-014
   text says `GET /health`; to avoid colliding with the root probe and to match
   the authenticated `/api/v1` surface Sonarr uses, the **health warnings list**
   lives at `GET /api/v1/health` — an array of items `{source, type:
   ok|warning|error, message, remediationHint}`. The delta spec records this
   disambiguation explicitly. Both are legitimate; they answer different
   questions (is the container alive? vs. what is wrong that an admin should act
   on?).

6. **One health-aggregation service feeds three shapes.** A
   `health/service.py` (new) computes a list of component health records from
   already-persisted / cheap-live state: `ProviderBackoff.health()` for
   ComicVine / each indexer / SAB / DDL provider (state ok / degraded /
   disabled-until + last-success/last-failure), root-folder existence +
   writability + free space, database integrity (last check result) + last
   backup age, scheduler running (from `scheduler.status()`), and disk space
   under a low-space threshold. From that one list it derives: (a) the
   FRG-API-014 `/api/v1/health` warnings list (only the non-ok items, each with a
   remediation hint); (b) the FRG-NFR-011 `/api/v1/system/health` full
   per-component view (every component with its state + timestamps). No new
   table — reads are over `provider_backoff`, the filesystem, and PRAGMA. The
   checks OWNED by other areas (indexer/SAB back-off) are read, not
   re-implemented, per the FRG-API-014 note "Health checks are produced by their
   owning areas; this owns aggregation + transport."

7. **Health surfacing is poll-first.** The System screens poll via React Query
   with a modest refetch interval (health is low-frequency; a component that
   recovers clears on the next poll — satisfying FRG-NFR-011's "recovery clears
   it without restart"). No new WS event is required; if a cheap invalidation
   hook already fires on a back-off transition it MAY nudge a refetch, but that
   is an accelerator, not a dependency. This keeps the change from touching the
   WS contract.

8. **`/system/task` list + force-run reuse the scheduler verbatim.**
   `GET /api/v1/system/task` returns `scheduler.status()` enriched with each
   task's command name and a display label. `POST /api/v1/system/task/{name}`
   calls `scheduler.force_run(name)` (404 on `UnknownTaskError`) and returns the
   enqueued command record (id + status) so the UI can track it to terminal —
   this is the force-run FRG-UI-016 needs, and it resets the timer (which a plain
   `POST /command` would not). "Back up now" is this endpoint against the
   `backup-database` task.

9. **`/system/status` is extended, not replaced.** Add runtime + path fields to
   the existing `SystemStatus` model: config dir, db path, backups dir,
   root-folder count, process start time / uptime, python version, OS/platform.
   Paths are the managed `/config` locations only — no secrets, no config values
   that carry credentials. The existing `{version, commit, build_date}` fields
   stay byte-for-byte so existing consumers/tests keep passing.

10. **Frontend System area.** A `System` nav group with Status / Health / Tasks
    screens (Sonarr shape). Status: version/build + paths/runtime table. Health:
    the warnings list with type icons + remediation hints, and the per-component
    state table (ok / degraded with disabled-until countdown / error). Tasks: the
    scheduled-task table (name, interval, last run, next run) with a per-row
    force-run button and a prominent "Back up now" affordance on the
    `backup-database` row; a force-run reflects the returned command status to
    terminal. All read-only except the force-run POSTs.

## Risks / Trade-offs

- **[A backup is a plaintext-credential artifact]** → the headline accepted risk
  (RISK-041). Bounded by keeping backups strictly under `/config` (no off-box
  transport, no download endpoint), `/config`'s non-root ownership, and never
  logging secret values. Encryption-at-rest deferred to M5 (FRG-AUTH-008). This
  is declared in the proposal and added to the risk register as a task.
- **[Restore-marker hook swaps files → path-confinement surface]** → the marker's
  named directory MUST resolve under `/config/backups` via the existing
  `security.paths` confinement; an absolute/traversal target is refused, the
  live DB is snapshotted aside first, and the backup's integrity is verified
  before the swap. Threat-model delta covers this.
- **[Integrity check cost]** → `quick_check` at startup is bounded and fast;
  the full `integrity_check` rides the (infrequent, ~daily) backup job, off the
  request path. Acceptable at single-user DB sizes.
- **[Backup on a large DB blocks the pp/default worker briefly]** → it runs on a
  worker pool via the command queue (not in a request), holds only its own
  `exclusivity_group`, and checkpoint+backup on a home-library-sized SQLite DB is
  seconds. Revisit only if a realistic-size test shows a problem.
- **[Two `/health` endpoints confuse]** → deliberate and documented: root
  `/health` = liveness for Docker; `/api/v1/health` = actionable warnings for the
  admin. The delta notes and manual both spell out the split.
- **[Scheduled + pre-migration pools share the backups dir]** → distinct
  `scheduled-*` / `pre-migration-*` prefixes and prefix-scoped pruning keep their
  retentions independent; a test asserts pruning one pool never touches the
  other.

## Migration Plan

No schema migration. New config keys (`db_backup_interval_seconds`,
`db_scheduled_backup_retention`) default to safe values, so an existing
`/config` needs no change. Rollback = revert the merge; the backup task, health
service, and System screens are additive. The restore-marker hook is inert
unless a `/config/restore-from` marker is present.

## Open Questions

None blocking. Implementation-time calls, each with a stated default:
1. **Backup interval / retention defaults** — daily / keep 7. Tune via config if
   the library churns faster.
2. **Low-disk-space threshold** for the health warning — default a small
   absolute floor (e.g. < 1 GiB free on the `/config` or a root-folder volume);
   make it a config key if it proves noisy.
3. **Whether the config file is a single file or a directory** to copy alongside
   the DB — follow whatever `config.py` actually persists (single YAML/INI
   today); the helper copies the resolved config path.
