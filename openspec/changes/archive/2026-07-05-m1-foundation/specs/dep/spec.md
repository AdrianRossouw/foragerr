## MODIFIED Requirements

### Requirement: FRG-DEP-002 — all persistent state under /config

The system SHALL write all persistent state — database, config file, logs, backups, caches — under `/config`, and SHALL treat the container filesystem as disposable.

- **Milestone**: M1
- **Source**: mylar-feature-surface.md §8 DEP; linuxserver.io convention (CLAUDE.md).
- **Notes**: The deployment-side twin of DB's "single database under /config" — keep both; one governs the volume contract, the other the data model.

#### Scenario: All persistent artifacts created under the configured config dir

- **WHEN** the application starts against a fresh, empty config directory (configurable; `/config` in the container, any path locally) and runs long enough to initialize
- **THEN** the SQLite database, the generated config file, and the log directory all exist under that config directory, and no application-state file (DB, config, log, backup) is created outside it (OS temp dirs excluded)

#### Scenario: State survives replacing the application instance

- **WHEN** the application is stopped, its process/working environment discarded, and a new instance is started pointing at the same config directory
- **THEN** the new instance starts with identical persisted state — same database contents, same effective configuration — with no re-initialization of existing data

#### Scenario: Config directory location is configurable

- **WHEN** the application is started with a non-default config-directory setting (env var or CLI) pointing at an alternate path
- **THEN** all persistent state is written under that alternate path and nothing is written under the default location

### Requirement: FRG-DEP-003 — configuration via environment variables and config file

The system SHALL read configuration from a versioned config file under `/config` with environment-variable overrides taking precedence, and SHALL document every setting with its default; secrets (API keys, credentials) SHALL be supplied via environment variables or the config file, never baked into the image.

- **Milestone**: M1
- **Source**: mylar-feature-surface.md §7 (config surface, 34 sections — foragerr's is deliberately far smaller); CLAUDE.md Secrets section.
- **Notes**: Env-over-file precedence is the container-native divergence from Mylar's ini-only model. Validation of the values is baselined under NFR (config validation) — dedup hint.

#### Scenario: First run generates a documented config file

- **WHEN** the application starts against a fresh config directory containing no config file
- **THEN** it generates `config.yaml` in the config directory containing every setting with its default value and an explanatory comment, and the application runs with those defaults

#### Scenario: Config file value takes effect

- **WHEN** a setting (e.g., log level) is changed in `config.yaml` and the application is restarted with no corresponding environment variable set
- **THEN** the application runs with the file's value rather than the built-in default

#### Scenario: Environment variable overrides the config file

- **WHEN** the same setting is present in `config.yaml` and also set via its `FORAGERR_*` environment variable with a different value
- **THEN** the environment variable's value wins, observably (e.g., in effective log verbosity or the reported effective config)

#### Scenario: Secrets have no baked-in defaults

- **WHEN** the application starts with no secret values supplied via environment or config file
- **THEN** every secret-typed setting is empty/unset — no default key or credential value exists anywhere in the codebase or generated config — and the generated `config.yaml` contains only empty/commented placeholders for secrets

### Requirement: FRG-DEP-005 — secrets never in image or repository

The build and release process SHALL guarantee that no secret (ComicVine, DogNZB, NZB.su, SABnzbd keys, credentials) is present in the git repository, the Docker build context, or any image layer; secrets enter only at runtime.

- **Milestone**: M1
- **Source**: CLAUDE.md Secrets section; mylar-feature-surface.md §7 (Mylar's at-rest obfuscation — which foragerr must better, see AUTH).
- **Notes**: Process-enforceable (CI secret scan). Runtime at-rest protection of stored secrets is AUTH's requirement; log redaction is NFR's — three distinct layers, do not merge.

#### Scenario: Repository secret scan passes

- **WHEN** an automated secret scan runs over the full git history and working tree in CI
- **THEN** the scan reports no secret material (API keys, tokens, credentials), and the scan is a required, failing-blocks-merge check

#### Scenario: Secret-bearing files are excluded from version control

- **WHEN** `.env` (or any local secrets file) exists in the working tree with real key values
- **THEN** `git status` shows it as ignored, and attempting to stage it is prevented by the ignore rules

#### Scenario: Secrets reach the process only at runtime

- **WHEN** the application source tree and packaged artifacts are searched for any configured secret value
- **THEN** nothing is found — the running process obtains secrets exclusively from its runtime environment variables or the operator-provided config file in the config directory

### Requirement: FRG-DEP-006 — structured logging

The system SHALL emit structured logs (level, timestamp, logger, event fields) to stdout for container capture and to a size-rotated file under `/config/logs`, with the log level configurable at runtime without rebuild.

- **Milestone**: M1
- **Source**: mylar-feature-surface.md §7 (Logs section) and §8 (exception capture to DB); sonarr-architecture.md §7.1 (Logs resource).
- **Notes**: Secret redaction within logs is NFR. A log-viewer API/UI page is API/UI AREA backlog; this requirement owns emission, not display.

#### Scenario: Structured lines on stdout

- **WHEN** the application starts and handles a request
- **THEN** each stdout log line is a parseable key-value structured record containing at least timestamp, level, logger name, and event message

#### Scenario: Rotating log file under the config dir

- **WHEN** the application runs and emits enough log volume to exceed the configured max file size
- **THEN** `logs/foragerr.log` exists under the config directory, is rotated at the size limit, and the number of retained rotated files does not exceed the configured backup count

#### Scenario: Log level configurable without rebuild

- **WHEN** the log level is changed via config file or `FORAGERR_*` env var (e.g., INFO to DEBUG) and the application is restarted
- **THEN** the emitted verbosity changes accordingly — DEBUG-level events appear that were absent at INFO — with no code or build change

### Requirement: FRG-DEP-007 — health endpoint

The system SHALL expose an unauthenticated HTTP health endpoint reporting liveness and readiness (DB reachable/integrity, scheduler running, migration state), suitable for Docker HEALTHCHECK, returning non-2xx when unhealthy.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.1 (Health resource, CheckHealth task); mylar-feature-surface .md §8 (BACKENDSTATUS-style flags — mylar-comicvine.md §1.3).
- **Notes**: Exempt from M3 auth by design (record in STRIDE when AUTH lands). Rich per-provider health (CV/indexer status) is NFR observability; this endpoint is the container-level check.

#### Scenario: Healthy instance returns 200 with component statuses

- **WHEN** `GET /health` is requested on a running instance with the database reachable and the scheduler running
- **THEN** the response is 200 with a body reporting overall liveness and per-component statuses (database, scheduler, migration state)

#### Scenario: Unhealthy component flips the endpoint non-2xx

- **WHEN** a monitored component is unhealthy (e.g., the database is unreachable or the scheduler is stopped)
- **THEN** `GET /health` returns a non-2xx status and the body identifies the failing component

#### Scenario: No credentials required

- **WHEN** `GET /health` is requested with no authentication headers, cookies, or API key
- **THEN** the endpoint responds normally — it is reachable anonymously, making it usable as a Docker HEALTHCHECK probe

### Requirement: FRG-DEP-008 — graceful shutdown

The system SHALL handle SIGTERM/SIGINT by stopping intake of new work, draining or checkpointing in-flight work within a bounded grace period (< 30 s, s6/Docker compatible), closing the database cleanly (WAL checkpoint), and exiting 0.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §6 (command lifecycle); mylar-ddl.md §1.6 (sentinel shutdown); linuxserver s6 convention (CLAUDE.md).
- **Notes**: Process half of the shutdown story; SCHED's graceful-queue-drain is the queue half.

#### Scenario: SIGTERM produces a clean, bounded exit

- **WHEN** SIGTERM is sent to a running instance
- **THEN** the process stops accepting new work, completes shutdown within the bounded grace period (< 30 s), and exits with code 0

#### Scenario: Command queue drains before exit

- **WHEN** SIGTERM arrives while queued/in-flight commands exist
- **THEN** the shutdown sequence invokes the scheduler's graceful queue drain (per FRG-SCHED-011) before process exit, and no new commands are admitted after the signal

#### Scenario: Database closed cleanly with WAL checkpoint

- **WHEN** the process shuts down via SIGTERM and is subsequently restarted against the same config directory
- **THEN** the SQLite WAL was checkpointed at shutdown (no stale `-wal` growth carried over) and the restart logs show no recovery warnings or interrupted-state anomalies

### Requirement: FRG-DEP-009 — no self-update (explicit divergence from Mylar)

The system SHALL NOT implement any self-update mechanism (git pull, tarball fetch, in-place upgrade); upgrades occur exclusively by deploying a new image against the same `/config` volume.

- **Milestone**: M1
- **Source**: mylar-feature-surface.md §8 ("git-based self-update with commits-behind detection and source-tarball fallback") — deliberately NOT carried over.
- **Notes**: Deliberate divergence, container-native. Removes Mylar's Git config section, update job, and versioncheck machinery from scope entirely. A passive "newer image available" check is backlog at most.

#### Scenario: No update code path exists

- **WHEN** the codebase is reviewed/scanned for self-update machinery (git pull, tarball/release fetch, in-place code replacement, restart-into-new-version logic)
- **THEN** no such code path, scheduled job, API endpoint, or config setting exists

#### Scenario: Version is fixed at build

- **WHEN** a running instance is inspected over its lifetime
- **THEN** the reported version and build metadata never change while the process runs — the only documented upgrade procedure is deploying a new build against the same config directory

### Requirement: FRG-DEP-010 — version and build info

The system SHALL expose its version, build/commit identifier, and build date via an API endpoint and in the startup log line.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.1 (System/Status); mylar-feature-surface.md §8 (mylar_info table, version check).
- **Notes**: Cheap, and required for supportability once self-update is removed — the version string is the only way to know what's deployed.

#### Scenario: Version endpoint reports build metadata

- **WHEN** the system-status API endpoint is requested on a running instance
- **THEN** the response includes the semantic version, the build/commit identifier, and the build date, matching the values baked in at build time

#### Scenario: Startup log line carries version info

- **WHEN** the application starts
- **THEN** an early startup log record contains the same version, commit identifier, and build date as the API reports

#### Scenario: Metadata degrades gracefully outside a built artifact

- **WHEN** the application runs from a source checkout where build metadata was not injected (local uvicorn development)
- **THEN** the endpoint and startup log still respond with well-defined placeholder values (e.g., "dev"/"unknown") rather than erroring or omitting the fields
