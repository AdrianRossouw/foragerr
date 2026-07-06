# ui — delta for m2-ops-health-backups

## MODIFIED Requirements

### Requirement: FRG-UI-016 — System status and tasks screens

The UI SHALL provide a System area with three screens: a Status screen (application version and build info, managed paths, and runtime info), a Health screen (current health warnings with remediation hints plus the per-component health table with each component's state — ok / degraded with its disabled-until countdown / error), and a Tasks screen (the scheduled-task table with last/next run and per-task force-run buttons, including a prominent "Back up now" action on the backup task). Force-running a task SHALL reflect the returned command's status until it reaches a terminal state.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §7.4 (System/{Status, Tasks}), §7.1 Health; mylar-feature-surface.md §SCHED (force-run from UI, jobhistory).
- **Notes**: Lives in a dedicated System nav group (Sonarr shape). Reads are poll-first via React Query (health clears on the next poll when a component recovers — FRG-NFR-011). Status shows only managed `/config` paths and runtime — never secrets (FRG-API-014). The Tasks force-run POSTs to `POST /api/v1/system/task/{name}` (resets the timer, returns the command id to track). The Health screen renders `GET /api/v1/health` warnings (with hints) and the `GET /api/v1/system/health` per-component table. Log-viewer screen stays milestone B — server-side log files suffice for a single admin.

#### Scenario: Status screen shows version, paths, and runtime

- **WHEN** the System → Status screen loads
- **THEN** it renders the application version/build info, the managed paths (config dir, database path, backups dir, root-folder count), and runtime info (uptime, python/OS), and displays no secret values

#### Scenario: Health screen shows warnings with remediation and per-component state

- **WHEN** an indexer is in failure back-off and the System → Health screen loads
- **THEN** the warnings list shows the failing indexer with its remediation hint, the per-component table shows that indexer `degraded` with its disabled-until countdown, and once it recovers a subsequent poll clears the warning without a manual refresh or restart

#### Scenario: Tasks screen force-runs a task and tracks its command

- **WHEN** the user clicks a task's force-run button (or "Back up now" on the backup task) on the System → Tasks screen
- **THEN** `POST /api/v1/system/task/{name}` is issued and the row reflects the returned command status as it progresses to terminal, and the task's last-run/next-run update afterwards

#### Scenario: Healthy system Health screen is explicitly clear

- **WHEN** no component is unhealthy and the Health screen loads
- **THEN** it shows an explicit "all healthy" state (distinct from a loading or error state) and the per-component table shows every component `ok`
