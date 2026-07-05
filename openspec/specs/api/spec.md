# API — Backend HTTP API Specification

## Purpose

Baseline requirements for backend http api, mined from the
Phase 1 reference research (`docs/research/`). Baseline depth per the Phase 2 scope
decision: SHALL + coarse acceptance; scenario-level elaboration happens in the
milestone change that implements each requirement (FRG-PROC-003, FRG-PROC-009).
## Requirements
### Requirement: FRG-API-001 — Versioned, OpenAPI-documented REST API

The backend SHALL expose all application functionality through a versioned REST API under a single version prefix (`/api/v1`), with a machine-readable OpenAPI document served by the application that describes every endpoint, request/response schema, and error shape.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.1 (route prefix `api/v3/`), §7.2 conventions; foragerr stack is FastAPI which generates OpenAPI natively.
- **Notes**: Sonarr's API is versioned but not OpenAPI-documented — deliberate divergence, free with FastAPI. All other API requirements inherit this prefix.

#### Scenario: App factory builds the application with all routes under the version prefix

- **WHEN** the FastAPI application is constructed via the app factory and its route table is enumerated
- **THEN** every application route path (excluding the health endpoint owned by DEP) begins with `/api/v1`, and constructing a second app instance via the factory yields an independent, equivalently routed application (no import-time singleton state)

#### Scenario: OpenAPI document is served and accurate

- **WHEN** `GET /api/v1/openapi.json` is requested
- **THEN** it returns a valid OpenAPI 3.x document whose paths exactly cover the registered routes (every registered route appears; no documented path lacks a registered route), including request/response schemas and the standard error shape; no UI-consumed endpoint exists outside the version prefix

### Requirement: FRG-API-002 — Standard error and resource conventions

Every API resource SHALL carry an integer `id`, use JSON request/response bodies, follow REST verb semantics (GET read, POST create, PUT full update with id from route, DELETE remove), and return validation failures as structured 400-level responses naming the offending field.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.2 (`RestController<TResource>` + per-verb FluentValidation, resources carry `id`, PUT id from route).
- **Notes**: Pydantic models are the FluentValidation equivalent. This is the base convention requirement other API requirements assume.

#### Scenario: Uniform error shape for all 4xx responses including validation failures

- **WHEN** a request triggers a 4xx — a PUT with an invalid field value (Pydantic validation failure), a GET for a nonexistent id (404), and a malformed JSON body
- **THEN** every response body has the uniform shape `{"message": <string>, "errors": [...]}`, with Pydantic validation errors mapped into `errors[]` entries that name the offending field; no FastAPI default `{"detail": ...}` shape leaks through

#### Scenario: Resource CRUD round-trip follows the conventions

- **WHEN** a CRUD round-trip is performed on at least one resource (POST create, GET read, PUT full update with id taken from the route path, DELETE remove)
- **THEN** the resource carries an integer `id` assigned by the system, all bodies are JSON, the PUT ignores/rejects a conflicting body id in favor of the route id, and GET after DELETE returns 404 in the uniform error shape

#### Scenario: Paged list endpoints use the shared paging envelope

- **WHEN** a paged list endpoint built on the shared paging-envelope helper is queried with `page`, `pageSize`, and a whitelisted `sortKey`/`sortDirection`
- **THEN** the response is the envelope `{page, pageSize, sortKey, sortDirection, totalRecords, records[]}` with correct `totalRecords` and correctly sorted, sliced `records[]`

#### Scenario: Unknown sort keys are rejected, never interpolated into SQL

- **WHEN** a paged endpoint is queried with a `sortKey` not on that endpoint's whitelist (including SQL metacharacter payloads such as `title; DROP TABLE--`)
- **THEN** the response is a 400 in the uniform error shape naming the parameter — not a 500 and not a silent default — and the helper's implementation maps whitelisted keys to fixed column expressions so the client-supplied string is never interpolated into an ORDER BY clause

### Requirement: FRG-API-003 — Series resources with ComicVine lookup

The API SHALL provide series endpoints: `GET /series` (library index), `GET/POST/PUT/DELETE /series/{id}`, and `GET /series/lookup?term=` performing a live ComicVine volume search returning candidate series with remote poster, year, publisher, and external id; POST accepts add options (root folder, monitoring strategy, format profile) as write-only fields.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.1 (Series + lookup), §7.3 SeriesResource shape, §1.2 add flow.
- **Notes**: Series add *behavior* (refresh chain, monitoring) is SER/META area; this requirement owns only the HTTP surface. Dedup hint: statistics aggregation mirrors Sonarr `SeriesStats/`.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Lookup by title returns ComicVine candidates; POSTing one creates a library series whose subsequent GET includes statistics (issue count, issue file count, size on disk).

### Requirement: FRG-API-004 — Issue resources with monitored toggle

The API SHALL provide issue endpoints returning per-issue resources (seriesId, issue number as decimal/string-safe value, title, cover date, monitored, hasFile, nested issue-file info) with a monitored-toggle update supporting both single-issue and bulk operations.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.1 (Episode get/monitor toggle), §7.3 EpisodeResource→IssueResource; §1.1 decimal/string issue numbers (`1.5`, `1.MU`).
- **Notes**: Issue numbers must not be modeled as integers in the resource schema — comics need `1.5`/annual forms (divergence from Sonarr's int episode numbers).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** `GET /issue?seriesId=` lists a series' issues; a bulk monitored update flips N issues in one request and is reflected on re-read.

### Requirement: FRG-API-005 — Command endpoint for background actions

The API SHALL execute every background action (refresh series, rescan, issue search, RSS sync, rename, etc.) via `POST /api/v1/command {name, ...params}` returning a trackable command resource (status queued/started/completed/failed, timestamps), with `GET /command` listing queued/running commands and `GET /command/{id}` for one.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.2 command endpoint, §6.1 command queue (persisted, de-duplicated, prioritized).
- **Notes**: Command queue internals (persistence, dedup, workers) are backbone/SCHED area; this owns the HTTP contract. Every UI "do work" button routes through this endpoint.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** POSTing `{name: "RefreshSeries", seriesIds: [...]}` returns 201 with a command id whose status transitions to completed and is observable via GET.

### Requirement: FRG-API-006 — Paging envelope for list endpoints

Paged list endpoints (queue, history, blocklist, wanted) SHALL return the envelope `{page, pageSize, sortKey, sortDirection, totalRecords, records[]}` and SHALL reject non-whitelisted sort keys.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.2 paging envelope (`Sonarr.Http/PagingResource.cs`), whitelisted sort keys.
- **Notes**: Whitelisted sort keys double as SQL-injection defense on ORDER BY — pairs with the OPDS parameterized-query requirement.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** `GET /queue?page=2&pageSize=10&sortKey=<valid>` returns the envelope with correct totalRecords; an invalid sortKey yields a 4xx, not a 500 or silent default.

### Requirement: FRG-API-007 — Queue endpoint backed by tracked downloads

The API SHALL expose a paged `GET /queue` built from tracked downloads (not live client polling per request), each record carrying seriesId/issueId, nested series/issue, size/sizeleft, tracked-download status (ok/warning/error) and state, status messages, downloadId, client and indexer names, and estimated completion; with `DELETE /queue/{id}` supporting remove (optionally deleting data and/or blocklisting).

- **Milestone**: M1
- **Source**: sonarr-architecture.md §4.4 queue tracking loop and QueueService, §7.3 QueueResource shape, §7.1 queue actions.
- **Notes**: The tracking state machine itself is DL area; this owns the read/remove HTTP surface. "Nothing user-facing polls SAB directly" is the load-bearing property.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A grabbed release appears in `GET /queue` with downloading state within one tracking cycle; DELETE removes it from the queue and (when requested) from the download client.

### Requirement: FRG-API-008 — Release endpoint: interactive search with cached grab

The API SHALL provide `GET /release?issueId=` performing a live interactive search that returns every decision — approved, temporarily rejected, and rejected — each with human-readable rejection reasons, quality/format, score, indexer, size, and age; results SHALL be cached server-side (~30 min, keyed indexerId+guid) so that `POST /release {guid, indexerId}` grabs from cache and returns a clear "search again" error when the cache entry has expired.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.2 release endpoint semantics ("Copy this exactly"), §2.4 interactive search returning rejected decisions.
- **Notes**: This is the vertical slice's "search → grab" contract. Rejection reasons come from the decision engine (SRCH/decision area) — this owns transport only.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A search for an issue returns a mixed list including rejected entries with reasons[]; POSTing an approved entry's guid grabs it; POSTing after cache expiry returns 404-class error, not a silent re-search.

### Requirement: FRG-API-009 — Provider schema and test endpoints

For each provider family (indexers, download clients, notification connections), the API SHALL expose `GET /<provider>/schema` returning implementation templates with typed `fields[]` (name, label, type, options, advanced flag) generated from the provider's settings model, plus `POST /<provider>/test` (and `/testall`) executing a live connectivity/credentials test and returning structured pass/fail with messages.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.2 provider schema pattern ("the UI settings forms are 100% driven by this"), §2.1 ThingiProvider; mylar-feature-surface.md §IDX provider CRUD.
- **Notes**: M1 needs indexer + download client schemas (slice requires a working Newznab indexer and SABnzbd); notification schema ships when NOTIF ships (M2) with zero new frontend code — that is the point of the pattern.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** `GET /indexer/schema` lists at least the Newznab implementation with its fields; `POST /indexer/test` against a wrong API key returns a failure message without persisting the config.

### Requirement: FRG-API-010 — WebSocket resource-change push

The backend SHALL expose a WebSocket endpoint broadcasting resource-change messages (`{name, action, resource}`) for at least queue, command, series, and issue-file changes, debounced (~100 ms), as the SignalR equivalent driving live UI updates.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §6.1 UI push (ModelEvent → SignalR), §6.2 asyncio equivalent (FastAPI WebSocket, debounced broadcast).
- **Notes**: M1 may scope broadcast coverage to queue+command (what the slice's "queue tracking" needs); remaining resources by M2. Auth on the WS endpoint is AUTH/M3.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** With a WS client connected, grabbing a release produces queue-updated messages without the client issuing any poll; a command status change produces a command message.

### Requirement: FRG-API-011 — History endpoint

The API SHALL expose a paged `GET /history` of pipeline events (grabbed, imported, download failed, deleted, renamed) each carrying eventType, sourceTitle, quality/format, date, downloadId, a per-event data dict, and nested series/issue, filterable by series and event type.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §7.1 History (paged), §7.3 HistoryResource, §4.3 (downloadId as join key).
- **Notes**: The history *records* are written in M1 (the DL pipeline depends on grab history); only the read API + screen are M2. Flag to orchestrator: if slice debugging wants it earlier, promoting to M1 is cheap.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** After a grab-and-import cycle, history contains a grabbed row and an imported row sharing the same downloadId.

### Requirement: FRG-API-012 — Wanted/missing endpoint

The API SHALL expose paged wanted endpoints listing monitored, published issues without files (missing) and, once format profiles have a cutoff, issues below cutoff — both derived at query time, not from a stored wanted status.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §1.1 ("wanted is derived"), §7.1 Wanted/Missing + Wanted/Cutoff; mylar-feature-surface.md §3 (Mylar's stored Wanted status — divergence).
- **Notes**: Deliberate divergence from Mylar: no stored per-issue Wanted status; adopt Sonarr's derived model. Cutoff-unmet half may lag to B if format profiles land late.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Unmonitoring an issue removes it from `GET /wanted/missing` without any explicit status write.

### Requirement: FRG-API-013 — Config resource endpoints

The API SHALL expose typed config resources (host, media management, naming, UI) as GET/PUT singletons so all settings changes flow through the documented API rather than ad-hoc form posts.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §7.1 Config/{host, mediamanagement, naming, ui}; mylar-feature-surface.md §7 (Mylar's 34-section ini — the anti-pattern being replaced).
- **Notes**: M1 runs on defaults + env vars per CLAUDE.md secrets policy; config endpoints arrive with the settings screens. Secret-valued fields must round-trip masked (dedup hint: DEP/AUTH areas own at-rest handling).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** `PUT /config/naming` changes the rename template and the change is visible in a subsequent GET and used by the next rename.

### Requirement: FRG-API-014 — System status, health, and task endpoints

The API SHALL expose `GET /system/status` (version, runtime info, paths), `GET /health` (list of current health warnings/errors such as failing indexers or unreachable clients), and `GET /system/task` (scheduled tasks with last/next run).

- **Milestone**: M2
- **Source**: sonarr-architecture.md §7.1 System/Status, System/Tasks, Health; §2.6 indexer back-off feeding health; mylar-feature-surface.md §8 jobhistory table.
- **Notes**: Health *checks* are produced by their owning areas (IDX, DL); this owns aggregation + transport.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Disabling the only configured indexer via failure back-off surfaces a health item; task list shows the RSS-sync schedule with next-run time.

### Requirement: FRG-API-015 — Manual import endpoint

The API SHALL expose manual-import endpoints that list candidate files under a given path with their would-be import decisions and rejection reasons, and accept user-corrected mappings (series/issue/format overrides) for execution through the same import pipeline as automatic imports.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §5.5 ManualImportService ("the escape hatch for every mapping failure"), §7.1 ManualImport.
- **Notes**: Resolution path for ImportBlocked queue items; pairs with the UI manual-import overlay requirement.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A file that fails automatic mapping appears in the manual-import listing with its rejection reason; submitting a corrected mapping imports it.

### Requirement: FRG-API-016 — Parse debug endpoint

The API SHALL expose `GET /parse?title=` returning the parsed issue info (series title, issue number, year, format, group) and the library mapping result for an arbitrary release title.

- **Milestone**: B
- **Source**: sonarr-architecture.md §7.1 (Parse debug endpoint), §2.5 release parsing.
- **Notes**: Pure developer/support convenience; trivially thin over the parser (SRCH area). Keep last so numbering leaves fundamentals first.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Posting a known-ambiguous release title returns the parser's structured interpretation without side effects.

