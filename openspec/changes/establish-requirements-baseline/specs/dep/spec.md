# dep Spec Delta

## ADDED Requirements


### Requirement: FRG-DEP-001 — Docker image per linuxserver.io conventions

The system SHALL be packaged as a single Docker image following linuxserver.io conventions: PUID/PGID environment variables mapping the runtime user, a single `/config` volume for all persistent state, s6-overlay-style (or compatible) init, and TZ support.

- **Milestone**: M1
- **Source**: mylar-feature-surface.md §8 DEP (Dockerfile + init scripts); CLAUDE.md deployment target (linuxserver.io conventions — project-level source).
- **Notes**: Deployment IS M1: the vertical slice ships as this image running on the owner's home server over Tailscale. Media library mounts (e.g., `/comics`, `/downloads`) are additional volumes but hold no application state.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** `docker run -e PUID=1000 -e PGID=1000 -e TZ=... -v ./config:/config -p 8789:8789 foragerr` starts healthy; files created under `/config` are owned by 1000:1000.

### Requirement: FRG-DEP-002 — all persistent state under /config

The system SHALL write all persistent state — database, config file, logs, backups, caches — under `/config`, and SHALL treat the container filesystem as disposable.

- **Milestone**: M1
- **Source**: mylar-feature-surface.md §8 DEP; linuxserver.io convention (CLAUDE.md).
- **Notes**: The deployment-side twin of DB's "single database under /config" — keep both; one governs the volume contract, the other the data model.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Destroying and recreating the container with the same `/config` volume restores identical behavior; a filesystem diff of the container layer after a soak run shows no app-state writes outside `/config` (tmp excluded).

### Requirement: FRG-DEP-003 — configuration via environment variables and config file

The system SHALL read configuration from a versioned config file under `/config` with environment-variable overrides taking precedence, and SHALL document every setting with its default; secrets (API keys, credentials) SHALL be supplied via environment variables or the config file, never baked into the image.

- **Milestone**: M1
- **Source**: mylar-feature-surface.md §7 (config surface, 34 sections — foragerr's is deliberately far smaller); CLAUDE.md Secrets section.
- **Notes**: Env-over-file precedence is the container-native divergence from Mylar's ini-only model. Validation of the values is baselined under NFR (config validation) — dedup hint.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Setting a value in the config file takes effect; setting the corresponding env var overrides it; `docker history`/image scan shows no secret material in any layer.

### Requirement: FRG-DEP-004 — versioned config-file migration

The system SHALL stamp the config file with a schema version and apply stepped migrations on upgrade, backing up the previous config file (with retention) before rewriting it, and preserving unknown-but-valid user values.

- **Milestone**: M2
- **Source**: mylar-feature-surface.md §7 ("versioned stepped config migrations (v6→v14/15)"; "automatic config backup before upgrade with retention").
- **Notes**: Mechanically parallel to DB migrations but a separate artifact and version counter. Irrelevant until the config schema first changes — hence M2, but baselined now so the version stamp exists from M1's first written config.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Starting a new version against an old config file produces a migrated file at the new version plus a retained backup of the original; user-set values survive.

### Requirement: FRG-DEP-005 — secrets never in image or repository

The build and release process SHALL guarantee that no secret (ComicVine, DogNZB, NZB.su, SABnzbd keys, credentials) is present in the git repository, the Docker build context, or any image layer; secrets enter only at runtime.

- **Milestone**: M1
- **Source**: CLAUDE.md Secrets section; mylar-feature-surface.md §7 (Mylar's at-rest obfuscation — which foragerr must better, see AUTH).
- **Notes**: Process-enforceable (CI secret scan). Runtime at-rest protection of stored secrets is AUTH's requirement; log redaction is NFR's — three distinct layers, do not merge.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Automated secret-scan of the repo and image layers in CI passes; a grep of image layers for configured key values finds nothing.

### Requirement: FRG-DEP-006 — structured logging

The system SHALL emit structured logs (level, timestamp, logger, event fields) to stdout for container capture and to a size-rotated file under `/config/logs`, with the log level configurable at runtime without rebuild.

- **Milestone**: M1
- **Source**: mylar-feature-surface.md §7 (Logs section) and §8 (exception capture to DB); sonarr-architecture.md §7.1 (Logs resource).
- **Notes**: Secret redaction within logs is NFR. A log-viewer API/UI page is API/UI AREA backlog; this requirement owns emission, not display.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** `docker logs` shows parseable structured lines; the rotating file caps at its configured size/count; changing the level env/config setting changes verbosity on restart.

### Requirement: FRG-DEP-007 — health endpoint

The system SHALL expose an unauthenticated HTTP health endpoint reporting liveness and readiness (DB reachable/integrity, scheduler running, migration state), suitable for Docker HEALTHCHECK, returning non-2xx when unhealthy.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.1 (Health resource, CheckHealth task); mylar-feature-surface .md §8 (BACKENDSTATUS-style flags — mylar-comicvine.md §1.3).
- **Notes**: Exempt from M3 auth by design (record in STRIDE when AUTH lands). Rich per-provider health (CV/indexer status) is NFR observability; this endpoint is the container-level check.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** `curl /health` returns 200 with component statuses on a healthy instance; stopping the scheduler or corrupting the DB flips it non-2xx; the image defines a HEALTHCHECK using it.

### Requirement: FRG-DEP-008 — graceful shutdown

The system SHALL handle SIGTERM/SIGINT by stopping intake of new work, draining or checkpointing in-flight work within a bounded grace period (< 30 s, s6/Docker compatible), closing the database cleanly (WAL checkpoint), and exiting 0.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §6 (command lifecycle); mylar-ddl.md §1.6 (sentinel shutdown); linuxserver s6 convention (CLAUDE.md).
- **Notes**: Process half of the shutdown story; SCHED's graceful-queue-drain is the queue half.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** `docker stop` completes within the grace period without SIGKILL; restart shows no interrupted-state anomalies and no WAL recovery warnings.

### Requirement: FRG-DEP-009 — no self-update (explicit divergence from Mylar)

The system SHALL NOT implement any self-update mechanism (git pull, tarball fetch, in-place upgrade); upgrades occur exclusively by deploying a new image against the same `/config` volume.

- **Milestone**: M1
- **Source**: mylar-feature-surface.md §8 ("git-based self-update with commits-behind detection and source-tarball fallback") — deliberately NOT carried over.
- **Notes**: Deliberate divergence, container-native. Removes Mylar's Git config section, update job, and versioncheck machinery from scope entirely. A passive "newer image available" check is backlog at most.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Code review confirms no update/restart-into-new-version pathway exists; the documented upgrade procedure is image redeploy; DB/config migrations then run per their requirements.

### Requirement: FRG-DEP-010 — version and build info

The system SHALL expose its version, build/commit identifier, and build date via an API endpoint and in the startup log line.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.1 (System/Status); mylar-feature-surface.md §8 (mylar_info table, version check).
- **Notes**: Cheap, and required for supportability once self-update is removed — the version string is the only way to know what's deployed.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** `GET /api/.../system/status` (shape per API AREA) returns version fields matching the image label; the first startup log line contains them.

### Requirement: FRG-DEP-011 — Tailscale-scoped exposure

The system SHALL bind its HTTP listener on a configurable address/port (default all interfaces inside the container) and SHALL be documented and operated as reachable only via the home server's Tailscale network in M1-M2, with no requirement to be internet-safe before AUTH (M3).

- **Milestone**: M1
- **Source**: CLAUDE.md (OPDS for iPad over Tailscale); mylar-feature-surface.md §8 AUTH (Mylar's interface host/port).
- **Notes**: This is the deployment-side statement of the accepted M1 no-auth risk (AUTH has the matching requirement). HTTPS/self-signed-cert generation from Mylar is NOT baselined — Tailscale provides transport security; revisit only if exposure model changes.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Deployment doc shows the Tailscale-only access pattern; the risk register records "no auth before M3, network-scoped exposure" as the compensating control.

### Requirement: FRG-DEP-012 — secrets-stripped diagnostic bundle

The system SHALL generate on demand a diagnostic bundle (config with secrets redacted, recent logs, schema/version info, job history summary) containing no secret material.

- **Milestone**: B
- **Source**: mylar-feature-surface.md §8 ("carepackage diagnostic zip with secrets stripped").
- **Notes**: Low priority for a single-user system but cheap and demo-friendly for the regulated- process narrative. Redaction machinery is shared with NFR log redaction — build once.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Generated bundle passes an automated scan for all configured secret values; bundle contains config, logs, and version info.
