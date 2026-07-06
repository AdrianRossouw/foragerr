## Why

M2 changes 1–4.5 built the daily loop (add/search/download/import, mass
ingestion, the review screens, and add-series acceleration). What is still
missing is the **operator's view of the running system** — the surfaces a
single admin needs to trust the tool with an unattended library:

1. **No scheduled backups.** The only database backups today are the
   event-triggered pre-migration copies (FRG-DB-003). A machine that never
   upgrades never backs up — a disk fault, a bad import, or a fat-fingered
   delete has no restore point. Mylar's "rolling versioned backups of DB+config
   with retention" (feature-surface §8) is a baselined M2 requirement
   (FRG-DB-009) that was registered but never elaborated or built.
2. **No supported restore path.** FRG-DB-010 promises "a documented, supported
   restore path from any retained backup." Right now there is neither a
   procedure nor a mechanism — a backup you cannot restore is not a backup.
3. **Integrity is unchecked.** FRG-DB-012 requires `PRAGMA integrity_check`/
   `quick_check` at startup and before each scheduled backup, surfacing failure
   as a health error instead of silently backing up (or running on) a corrupt
   database.
4. **Health is invisible.** FRG-NFR-011 (per-component health with
   last-success/last-failure and current state) and the aggregation transport
   FRG-API-014 (`system/status`, health warnings, `system/task`) plus their
   screen FRG-UI-016 are all registered M2 rows with only baseline-acceptance
   placeholders. The per-provider back-off state already exists
   (`ProviderBackoff`), the scheduler already exposes `status()`/`force_run()`,
   and `/system/status` already returns the build info — but there is no
   Sonarr-style *health warnings list*, no per-component health view, no
   scheduled-task screen, and no force-run buttons. This change turns the
   existing raw state into the operator-facing status/health/tasks surfaces.

Grouping these together is deliberate: scheduled backups run as a SCHED command
(so they belong in the task list), integrity checks feed the health surface,
and the health/task/status screens are one System area of the UI. They share
files and concepts; splitting them would duplicate the wiring.

## What Changes

- **Scheduled DB + config backups (FRG-DB-009)**: a new `backup-database` SCHED
  command + registered scheduled task that, on its interval, runs a full
  integrity check, WAL-checkpoints, writes a consistent copy of the database
  (SQLite backup API — never a file copy of a live WAL DB) **and** the config
  file to `/config/backups/scheduled-<timestamp>/`, then prunes the scheduled
  pool to a configurable rolling count. It reuses the exact
  checkpoint-then-`source.backup(destination)` primitive already proven by the
  pre-migration path; the two pools use distinct name prefixes
  (`pre-migration-*` vs `scheduled-*`) so their retentions never fight. Because
  it is a SCHED command it appears in job history and is force-runnable —
  "backup now" is simply force-running this task (FRG-SCHED-007), not a new
  bespoke endpoint.
- **Startup + pre-backup integrity checks (FRG-DB-012)**: `PRAGMA quick_check`
  at startup (fast, preserves the startup-time NFR) and a full
  `PRAGMA integrity_check` as the first step of every scheduled backup. A
  failure is surfaced as a persistent **health error** (not a silent continue);
  a corrupt database aborts the backup rather than overwriting the rolling pool
  with a copy of corruption.
- **Restore path (FRG-DB-010)**: a documented offline procedure (stop container,
  swap the DB + config file from a chosen backup, start) **plus** a startup-time
  restore hook driven by a `/config/restore-from` marker: on the next start the
  app validates the named backup's integrity, snapshots the current DB aside,
  swaps the backup in, and clears the marker — all while the DB is closed. There
  is deliberately **no live-restore endpoint** (a running single-writer SQLite
  process cannot safely swap the file it holds open — see design).
- **System status, health, and task endpoints (FRG-API-014)**: extend
  `GET /api/v1/system/status` with runtime info and paths (config dir, db path,
  backups dir, root-folder count, uptime, python/OS) — never secrets; add
  `GET /api/v1/health` (the Sonarr-style **health warnings list**: source, type
  ok/warning/error, message, remediation hint) distinct from the existing root
  `/health` liveness probe (DEP); add `GET /api/v1/system/task` (scheduled tasks
  with last/next run and the command each runs) and
  `POST /api/v1/system/task/{name}` (force-run → `scheduler.force_run`, returns
  the command id and resets the timer).
- **Observable component health (FRG-NFR-011)**: a health-aggregation service
  producing, from already-persisted state, both the FRG-API-014 warnings list
  and a richer `GET /api/v1/system/health` per-component view (ComicVine, each
  indexer, SAB/download clients, DDL provider, scheduler, database, root folders,
  disk space) each with `state` (ok / degraded / disabled-until) and
  last-success/last-failure timestamps. Reads reuse `ProviderBackoff.health()`,
  root-folder free-space, and the integrity/backup status — no new tracking
  tables. Surfaced by poll (React Query refetch); a component that recovers
  clears on the next poll without restart.
- **System status and tasks screens (FRG-UI-016)**: a System area with a Status
  screen (version, paths, runtime), a Health screen (current warnings with
  remediation hints, per-component state), and a Tasks screen (scheduled-task
  table with last/next run and per-task force-run buttons, including "Back up
  now").

## Capabilities

### New Capabilities

None. All six requirement IDs are pre-registered M2 rows; this change elaborates
their placeholder baseline-acceptance scenarios into real behavior.

### Modified Capabilities

- `db`: FRG-DB-009 (scheduled DB+config backups with rolling retention as a
  SCHED command — elaborated from placeholder), FRG-DB-010 (documented offline
  restore + startup restore-marker hook; no live endpoint), FRG-DB-012 (startup
  quick_check + pre-backup full integrity_check surfacing failure as health
  error).
- `api`: FRG-API-014 (system/status extended with runtime+paths; new
  `/api/v1/health` warnings list disambiguated from the root liveness `/health`;
  `/system/task` list + force-run).
- `ui`: FRG-UI-016 (System Status / Health / Tasks screens with force-run).
- `nfr`: FRG-NFR-011 (per-component health service + `/system/health` view over
  existing back-off / free-space / integrity state).

## Impact

- **Code**: backend — a new backup/restore module (reusing `db/migrations.py`'s
  checkpoint+backup primitive) exposing `backup-database` command + task, the
  startup quick_check and restore-marker hooks (`app.py` startup sequence), new
  config settings (backup interval + scheduled-backup retention); a new
  health-aggregation service and its `/api/v1/health` + `/api/v1/system/health`
  routers; `system/status` extension; `/system/task` list + force-run route.
  Frontend — a System area (Status / Health / Tasks screens) + nav group +
  force-run wiring. No changes to any SCHED/DEP requirement — the backup rides
  existing `register_command`/`register_task`/`force_run`; the root `/health`
  liveness probe is untouched.
- **DB**: none. No new tables or columns — scheduled tasks reuse the existing
  `scheduled_tasks` row; health reads existing `provider_backoff` state and
  live filesystem/PRAGMA queries. (Backups are files under `/config/backups/`,
  not rows.)
- **Security docs (FRG-PROC-006)**: this change adds credential-bearing
  artifacts (the DB and config file both store provider API keys in plaintext,
  now copied into rolling backup files) and a filesystem-swapping restore hook.
  Two security-docs items are REQUIRED and declared here as tasks: (1) a NEW
  **accepted-risk** row RISK-041 recording *plaintext provider credentials in
  backups* (see below); (2) a threat-model delta covering the backup artifact
  (info-disclosure) and the restore-marker hook (path-confinement — the marker
  names a backup directory that MUST resolve under `/config/backups` via the
  existing `security.paths` confinement, never an arbitrary path). No new
  listener is added (health/status/task endpoints ride the existing
  authenticated `/api/v1` surface and expose no secrets).
- **Manual (FRG-PROC-011)**: admin-facing and user-facing behavior both change.
  Declared sections (carried out as a task):
  - `docs/manual/admin/configuration.md` — scheduled-backup interval and
    retention settings, integrity checking, what a backup contains (and the
    plaintext-credentials caveat with a pointer to the risk register).
  - `docs/manual/admin/deployment.md` — the restore procedure (offline swap and
    the `/config/restore-from` marker hook), and where backups live under
    `/config`.
  - `docs/manual/user/web-ui.md` — the new System area (Status, Health with
    remediation hints, Tasks with force-run / "Back up now").
- **Dependencies / SOUP (FRG-PROC-012)**: none anticipated — everything uses the
  stdlib (`sqlite3`, `shutil`, `pathlib`, `platform`, `os.statvfs`) and existing
  in-repo infrastructure. If implementation elects a new dependency (e.g. a
  disk-usage helper), `docs/security/soup-register.md` is updated in the same
  change; the default expectation is `tools/soup_check.py` exits 0 unchanged.

## Accepted risk — plaintext provider credentials in backups

Per the owner's 2026-07-06 planning decision, this change records the following
as an **ACCEPTED** risk (RISK-041), added to `docs/security/risk-register.md`
as an implementation task:

> **RISK-041 — Plaintext provider credentials in database/config backups.** The
> scheduled backups (FRG-DB-009) copy the SQLite database and the config file
> verbatim; both persist provider secrets — the ComicVine API key, each Newznab
> indexer key (DogNZB, NZB.su), and the SABnzbd API key — in plaintext, because
> foragerr has no encryption-at-rest or secret store yet. Every backup file is
> therefore a credential-bearing artifact: read access to `/config/backups/` (or
> a copied-off backup) yields every configured provider key. **Decision:
> Accept** for M2–M4 on the same footing as the standing no-auth acceptance
> (RISK-020): the deployment is single-user, all state lives under the
> container-private `/config` volume, and exposure is Tailscale-scoped with no
> off-box backup transport in scope. Compensating controls: backups are written
> ONLY under `/config/backups/` (there is deliberately no cloud/remote/off-box
> backup feature and no HTTP endpoint that streams a backup out), they inherit
> the linuxserver.io non-root PUID/PGID ownership and permissions of `/config`,
> and credential values are never logged or echoed. Encryption-at-rest / a
> secret store that would let backups omit or encrypt credentials is explicitly
> **deferred to the M5 auth milestone (FRG-AUTH-008)**. **Review trigger:** any
> feature that moves a backup off the `/config` volume (scheduled off-box/cloud
> backup, a download-backup-over-HTTP endpoint) or any multi-user/shared
> deployment MUST revisit this before shipping.

## Non-goals

- **No encryption-at-rest / secret store for backups** — deferred to M5
  (FRG-AUTH-008); tracked by RISK-041 above.
- **No off-box / cloud / downloadable backups** — backups stay under `/config`;
  no HTTP endpoint streams a backup out (that would change the RISK-041 posture).
- **No live-restore endpoint** — restore is offline / startup-marker only
  (single-writer SQLite cannot safely swap its open file at runtime).
- **No library JSON export/import** (FRG-DB-011 is milestone B) — this is a
  binary DB backup, not the portable library document.
- **No metrics / telemetry endpoint** (no Prometheus, no counters surface) and
  **no notifications** (NOTIF area parked) — health is pull-only via the UI.
- **No log-viewer screen** (FRG-UI-016 note: milestone B; server-side log files
  suffice for a single admin).
- **No age-based backup pruning** — rolling **count**-based retention only
  (matches the existing `prune_backups`); an age policy is a later refinement.
- **No changes to the root `/health` liveness probe** (DEP) or to any SCHED
  requirement — the backup task rides existing scheduler infrastructure.

## Approval

Adrian pre-approved this change on 2026-07-06 under the M2/M3 standing
FRG-PROC-009 grant. His words, verbatim:

> keep going with m2/m3 and all their related changes as you go. I'll come check in later

Recorded per the M1-style standing-grant model; m2-ops-health-backups (M2
change 5) falls squarely within that grant's scope.
