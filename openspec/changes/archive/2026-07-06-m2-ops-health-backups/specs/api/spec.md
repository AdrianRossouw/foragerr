# api — delta for m2-ops-health-backups

## MODIFIED Requirements

### Requirement: FRG-API-014 — System status, health, and task endpoints

The API SHALL expose `GET /api/v1/system/status` (version, build info, runtime, and managed paths), `GET /api/v1/health` (a list of current health warnings/errors such as failing indexers, an unreachable download client, a failing integrity check, or a low-disk condition), `GET /api/v1/system/task` (scheduled tasks with last/next run and the command each runs), and `POST /api/v1/system/task/{name}` (force-run a scheduled task, returning the enqueued command). The `GET /api/v1/health` warnings list is distinct from the existing root `GET /health` liveness probe (DEP): the root probe answers "is the container alive?" for the Docker HEALTHCHECK; `/api/v1/health` answers "what is wrong that the admin should act on?". Status and health endpoints SHALL NOT expose any secret (provider keys, credentials).

- **Milestone**: M2
- **Source**: sonarr-architecture.md §7.1 System/Status, System/Tasks, Health; §2.6 indexer back-off feeding health; mylar-feature-surface.md §8 jobhistory table.
- **Notes**: Health *checks* are produced by their owning areas (IDX/DL back-off, DB integrity); this owns aggregation + transport (FRG-NFR-011 provides the per-component service). `system/status` is EXTENDED, not replaced — the existing `{version, commit, build_date}` fields stay and gain runtime + path fields (config dir, db path, backups dir, root-folder count, uptime, python/OS). Force-run reuses `scheduler.force_run` (FRG-SCHED-007): it enqueues immediately, resets the task timer, dedups, and returns the command id — which a plain `POST /command` would not. "Back up now" is `POST /api/v1/system/task/backup-database`. The `/api/v1/health` list items carry `{source, type: ok|warning|error, message, remediationHint}`.

#### Scenario: System status carries build info, runtime, and managed paths without secrets

- **WHEN** `GET /api/v1/system/status` is requested
- **THEN** the response includes the existing version/commit/build_date plus runtime info (uptime, python version, OS) and managed paths (config dir, database path, backups dir, root-folder count) — and contains no provider key, credential, or other secret value

#### Scenario: Health warnings list surfaces an actionable item with a remediation hint

- **WHEN** the only configured indexer is disabled by failure back-off and `GET /api/v1/health` is requested
- **THEN** the response lists a health item of type `warning`/`error` naming the failing indexer with a remediation hint, and a fully-healthy system returns an empty (or all-`ok`) list — this endpoint is separate from the root `/health` liveness probe, whose up/down behavior is unchanged

#### Scenario: Task list shows schedule state and the command each runs

- **WHEN** `GET /api/v1/system/task` is requested
- **THEN** each scheduled task (including `backup-database`) is listed with its interval, last-run, next-run, command name, and display label

#### Scenario: Force-run enqueues the task's command and returns it

- **WHEN** `POST /api/v1/system/task/backup-database` is requested
- **THEN** the backup command is enqueued now (timer reset, dedup applied), the response carries the enqueued command's id and status so the client can track it to terminal, and an unknown task name returns a 404
