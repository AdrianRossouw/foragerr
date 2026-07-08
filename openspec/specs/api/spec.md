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

The API SHALL provide series endpoints: `GET /series` (library index), `GET/POST/PUT/DELETE /series/{id}`, and `GET /series/lookup?term=` performing a live ComicVine volume search returning candidate series with remote poster, year, publisher, and external id; POST accepts add options (root folder, monitoring strategy, format profile) as write-only fields. Lookup SHALL distinguish outcome classes: a ComicVine authentication failure yields a structured error response (not an empty 200) carrying a machine-readable field discriminator so clients never classify by message prose, and the response envelope marks a degraded walk (`complete`) and a deliberately capped walk (`truncated`) as distinct conditions, both distinguishable from a clean empty result.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.1 (Series + lookup), §7.3 SeriesResource shape, §1.2 add flow.
- **Notes**: Series add *behavior* (refresh chain, monitoring) is SER/META area; this requirement owns only the HTTP surface. Dedup hint: statistics aggregation mirrors Sonarr `SeriesStats/`. Outcome-class distinction added in m2-lookup-error-surfacing. `deleteFiles=true` implemented in m2-daily-surfaces (was 501): files route through the recycle bin before rows are removed.

#### Scenario: Series index returns a paged envelope with whitelisted sort

- **WHEN** `GET /api/v1/series?page=1&pageSize=20&sortKey=title` is requested
- **THEN** the response is the paging envelope with `totalRecords` and `records[]`, and an unrecognized `sortKey` yields a 400 rather than a silent default or 500

#### Scenario: Lookup annotates ComicVine candidates without auto-adding

- **WHEN** `GET /api/v1/series/lookup?term=` is called with a title term
- **THEN** the response lists ComicVine candidates with remote poster, year, publisher, and external id plus plausibility annotations, and no library series row is created as a side effect

#### Scenario: Lookup surfaces ComicVine auth failure as a structured error

- **WHEN** `GET /api/v1/series/lookup?term=` is called and ComicVine rejects the request as unauthorized (missing, empty, or invalid API key)
- **THEN** the endpoint returns a structured upstream-error response (HTTP 503, message identifying the ComicVine credential as the cause, and an errors entry with `field="comicvine_api_key"` as the machine-readable discriminator) rather than `200` with an empty list; a warning log line names the credential failure, and neither the response nor the log line contains the API key value

#### Scenario: Lookup exposes walk completeness and truncation distinctly from clean-empty

- **WHEN** the lookup's pagination walk degrades on a non-auth failure (`complete=False`) or stops at the configured result cap (`truncated=True`)
- **THEN** the response envelope carries both flags distinctly so the client can tell a transient degrade (retry may help) from a deliberate cap (retry cannot help; narrow the term) and from a complete walk that genuinely matched nothing (which stays a `200` complete-and-empty response)

#### Scenario: POST validates and returns the queued refresh command id

- **WHEN** a valid `POST /api/v1/series` supplies a ComicVine volume, root folder, monitoring strategy, and format profile as write-only add options
- **THEN** the response creates the series and includes the command id of the queued refresh; an invalid volume, missing/invalid root folder, or a duplicate of an existing series is rejected with a structured 400 naming the offending field

#### Scenario: DELETE removes the row; deleteFiles routes files through the recycle bin

- **WHEN** `DELETE /api/v1/series/{id}` is called
- **THEN** the series row is removed without touching files (204); with `?deleteFiles=true` the request enqueues a file-deleting command (202 with the command resource) that holds the import-mutation exclusivity and runs off the event loop: every issue file is first moved to the recycle bin (or permanently deleted only when no bin is configured), each recorded as a `file_deleted` history event with `source=manual`, and only then are the rows removed — a mid-operation failure never leaves rows deleted while files were untouched, and a stranded compensation leftover is durably recorded with its bin path

### Requirement: FRG-API-004 — Issue resources with monitored toggle

The API SHALL provide issue endpoints returning per-issue resources (seriesId, issue number as decimal/string-safe value, title, cover date, monitored, hasFile, nested issue-file info) with a monitored-toggle update supporting both single-issue and bulk operations.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.1 (Episode get/monitor toggle), §7.3 EpisodeResource→IssueResource; §1.1 decimal/string issue numbers (`1.5`, `1.MU`).
- **Notes**: Issue numbers must not be modeled as integers in the resource schema — comics need `1.5`/annual forms (divergence from Sonarr's int episode numbers).

#### Scenario: Issue list is scoped by series and ordered by the persisted ordering key

- **WHEN** `GET /api/v1/issue?seriesId=` is requested for a series
- **THEN** the response is a paged envelope of that series' issues sorted by the persisted issue-ordering key, and each record's issue number is a string value (never an integer)

#### Scenario: Non-integer issue numbers round-trip as strings

- **WHEN** issues numbered `1.5` and `1.MU` are read back
- **THEN** those issue numbers are serialized exactly as the strings `1.5` and `1.MU`, not coerced to integers or floats

#### Scenario: Single monitored toggle updates one issue

- **WHEN** a `PUT` monitored-toggle sets `monitored` on a single issue
- **THEN** only that issue's monitored flag changes and the new value is reflected on re-read

#### Scenario: Bulk monitored update applies atomically

- **WHEN** a bulk `PUT` supplies `{issueIds, monitored}` for N issues
- **THEN** all N issues flip in a single request as one atomic operation (all or none), and the change is reflected on re-read

### Requirement: FRG-API-005 — Command endpoint for background actions

The API SHALL execute every background action (refresh series, rescan, issue search, RSS sync, rename, etc.) via `POST /api/v1/command {name, ...params}` returning a trackable command resource (status queued/started/completed/failed, timestamps), with `GET /command` listing queued/running commands and `GET /command/{id}` for one.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.2 command endpoint, §6.1 command queue (persisted, de-duplicated, prioritized).
- **Notes**: Command queue internals (persistence, dedup, workers) are backbone/SCHED area; this owns the HTTP contract. Every UI "do work" button routes through this endpoint.

#### Scenario: Valid command POST returns 201 with a trackable resource

- **WHEN** `POST /api/v1/command {name, ...payload}` is submitted with a known command name and valid payload
- **THEN** the response is 201 with a command resource carrying id, name, status, and timestamps

#### Scenario: Unknown name or invalid payload returns a uniform 400 error

- **WHEN** `POST /api/v1/command` is submitted with an unknown `name` or a payload that fails validation
- **THEN** the response is 400 in the uniform structured error shape identifying the problem, and no command is queued

#### Scenario: Command tracks to a terminal status via GET

- **WHEN** an accepted command is polled through `GET /api/v1/command/{id}`
- **THEN** its status transitions through the lifecycle to a terminal state (completed or failed) observable via GET

#### Scenario: Duplicate submission is deduplicated

- **WHEN** an equivalent command is submitted again while an identical one is already queued or running
- **THEN** the existing command resource (same id) is returned rather than a second distinct command, making the dedup semantics observable

### Requirement: FRG-API-006 — Paging envelope for list endpoints

Paged list endpoints (queue, history, blocklist, wanted) SHALL return the envelope `{page, pageSize, sortKey, sortDirection, totalRecords, records[]}` and SHALL reject non-whitelisted sort keys.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.2 paging envelope (`Sonarr.Http/PagingResource.cs`), whitelisted sort keys.
- **Notes**: Whitelisted sort keys double as SQL-injection defense on ORDER BY — pairs with the OPDS parameterized-query requirement.

#### Scenario: Series and issue list endpoints return the shared envelope

- **WHEN** the series list and issue list endpoints are requested with paging parameters
- **THEN** each responds with the envelope `{page, pageSize, sortKey, sortDirection, totalRecords, records[]}` and `totalRecords` reflects the full unpaged count

#### Scenario: Unknown sortKey is rejected with 400

- **WHEN** a list endpoint is called with a `sortKey` not on its whitelist
- **THEN** the response is 400, not a 500 or a silent fallback to a default sort

#### Scenario: Whitelisted sort keys map to fixed column expressions

- **WHEN** a request supplies a valid whitelisted `sortKey`
- **THEN** ordering is applied via a fixed pre-defined column expression mapped from the key, with the client-supplied string never interpolated into the ORDER BY clause

### Requirement: FRG-API-007 — Queue endpoint backed by tracked downloads

The API SHALL expose a paged `GET /queue` built from tracked downloads (not live client polling per request), each record carrying seriesId/issueId, nested series/issue, size/sizeleft, tracked-download status (ok/warning/error) and state, status messages, downloadId, client and indexer names, and estimated completion; with `DELETE /queue/{id}` supporting remove (optionally deleting data and/or blocklisting).

- **Milestone**: M1
- **Source**: sonarr-architecture.md §4.4 queue tracking loop and QueueService, §7.3 QueueResource shape, §7.1 queue actions.
- **Notes**: The tracking state machine itself is DL area; this owns the read/remove HTTP surface. "Nothing user-facing polls SAB directly" is the load-bearing property.

#### Scenario: Paged envelope over tracked_downloads joined to library

- **WHEN** `GET /api/v1/queue` is requested
- **THEN** it returns the standard paged envelope whose records are built from `tracked_downloads` joined to series/issues, each carrying seriesId/issueId, nested series/issue, size/sizeleft, status (ok/warning/error), state, status messages, downloadId, client and indexer names, and estimated completion

#### Scenario: Never a live client call at request time

- **WHEN** the queue endpoint serves a request
- **THEN** it reads only persisted tracked-download state and makes no live download-client call, so a grabbed release appears with downloading state within one tracking cycle rather than on demand

#### Scenario: import_pending and import_blocked are visible

- **WHEN** tracked downloads are in import_pending or import_blocked state
- **THEN** they appear in the `GET /queue` result with those states and their status messages, giving the user visibility into items awaiting or blocked from import

#### Scenario: DELETE removes with optional blocklist

- **WHEN** `DELETE /api/v1/queue/{id}?blocklist=<bool>` is called (optionally requesting data deletion)
- **THEN** the item is manually removed from the queue, the download client is instructed to remove it (and its data when requested), and a blocklist row is written when `blocklist=true`

### Requirement: FRG-API-008 — Release endpoint: interactive search with cached grab

The API SHALL provide `GET /release?issueId=` performing a live interactive search that returns every decision — approved, temporarily rejected, and rejected — each with human-readable rejection reasons, quality/format, score, indexer, size, and age; results SHALL be cached server-side (~30 min, keyed indexerId+guid) so that `POST /release {guid, indexerId}` grabs from cache and returns a clear "search again" error when the cache entry has expired.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.2 release endpoint semantics ("Copy this exactly"), §2.4 interactive search returning rejected decisions.
- **Notes**: This is the vertical slice's "search → grab" contract. Rejection reasons come from the decision engine (SRCH/decision area) — this owns transport only.

#### Scenario: Live search returns every decision including rejections, sorted by the comparator

- **WHEN** a client calls `GET /api/v1/release?issueId=<id>`
- **THEN** a live multi-indexer search runs and the response includes every decision — approved, temporarily rejected, and rejected — each carrying user-visible rejection reasons, quality/format, score, indexer, size, and age, and the rows are ordered by the decision comparator

#### Scenario: Response rows carry the indexerId+guid cache key and are cached ~30 min

- **WHEN** a search response is returned
- **THEN** each row carries its `indexerId` + `guid` cache key, and the results are held in a server-side cache for approximately 30 minutes with housekeeping that prunes expired entries

#### Scenario: POST on a cache hit enqueues the grab command and returns it

- **WHEN** a client calls `POST /api/v1/release {indexerId, guid}` while a matching cache entry is live
- **THEN** the endpoint enqueues the grab command (inert until change 5) and returns that command resource, without re-running a search

#### Scenario: POST on a cache miss or expiry returns a uniform 404-class error, never a silent re-search

- **WHEN** a client calls `POST /api/v1/release {indexerId, guid}` for a key that is absent or whose cache entry has expired
- **THEN** the endpoint returns a deterministic 404-class response in the uniform error shape and does not silently re-run the search

### Requirement: FRG-API-009 — Provider schema and test endpoints

For each provider family (indexers, download clients, notification connections), the API SHALL expose `GET /<provider>/schema` returning implementation templates with typed `fields[]` (name, label, type, options, advanced flag) generated from the provider's settings model, plus `POST /<provider>/test` (and `/testall`) executing a live connectivity/credentials test and returning structured pass/fail with messages.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.2 provider schema pattern ("the UI settings forms are 100% driven by this"), §2.1 ThingiProvider; mylar-feature-surface.md §IDX provider CRUD.
- **Notes**: M1 needs indexer + download client schemas (slice requires a working Newznab indexer and SABnzbd); notification schema ships when NOTIF ships (M2) with zero new frontend code — that is the point of the pattern.

#### Scenario: Schema endpoint returns field metadata sufficient to render the form with zero per-implementation frontend code

- **WHEN** a client calls `GET /api/v1/indexer/schema`
- **THEN** the response lists each indexer implementation with typed `fields[]` metadata (order, name, type, label, help, required flag, secret flag, select options for enumerated fields, advanced flag) sufficient for the settings form to be rendered generically — fields in a stable declared order, enumerated types carrying their options inline — with no per-implementation frontend code

#### Scenario: Secret fields are write-only and never echoed in GET responses

- **WHEN** a schema or configured-provider resource containing a secret field (e.g. an API key) is returned from a GET
- **THEN** the secret field value is never echoed back — it is presented as write-only — while its `secret` flag is still surfaced in the field metadata

#### Scenario: Test endpoint runs a live caps probe and returns success or a field-precise failure

- **WHEN** a client calls `POST /api/v1/indexer/test` with a configuration
- **THEN** the endpoint executes the live capabilities probe and returns either success or a field-precise failure rendered in the uniform error shape, without persisting the configuration on failure

### Requirement: FRG-API-010 — WebSocket resource-change push

The backend SHALL expose a WebSocket endpoint broadcasting resource-change messages (`{name, action, resource}`) for at least queue, command, series, and issue-file changes, debounced (~100 ms), as the SignalR equivalent driving live UI updates.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §6.1 UI push (ModelEvent → SignalR), §6.2 asyncio equivalent (FastAPI WebSocket, debounced broadcast).
- **Notes**: M1 may scope broadcast coverage to queue+command (what the slice's "queue tracking" needs); remaining resources by M2. Auth on the WS endpoint is AUTH/M3.

#### Scenario: Resource change is pushed without polling

- **WHEN** a client is connected to `/api/v1/ws` and a release is grabbed
- **THEN** the client receives a `{name, action, resource}` JSON message for the queue change without issuing any HTTP poll, and a command status change produces a corresponding command message

#### Scenario: Events are batched and debounced per (name, action)

- **WHEN** the event bus emits a burst of changes for the same (name, action) within ~100 ms
- **THEN** the subscriber coalesces them and broadcasts at most one batched message for that (name, action) after the debounce window rather than one message per underlying event

#### Scenario: Slow client is dropped and never blocks the bus

- **WHEN** one connected client stops draining its socket while events continue to flow
- **THEN** that socket's per-socket send queue fills, the slow client is dropped/closed, and other clients and the event bus continue delivering without stalling

#### Scenario: Reconnecting client resumes receiving

- **WHEN** a client disconnects and later reconnects to `/api/v1/ws`
- **THEN** it begins receiving subsequent resource-change broadcasts again; the endpoint enforces no auth in M1 (Origin validation is deferred to FRG-SEC-005/M3, recorded as a residual risk)

### Requirement: FRG-API-011 — History endpoint

The API SHALL expose a paged `GET /history` of pipeline events (grabbed, imported, upgrade-replaced, import-blocked/failed, download-failed, deleted, renamed) each carrying eventType, sourceTitle, date, downloadId, a per-event data dict, and nested series/issue, filterable by series and event type. The `import_history` table is the single feed source: grab and download-failure writers land their events there (the operational `grab_history` match-key table is unchanged), and an identical blocked outcome for the same download never duplicates its history row.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §7.1 History (paged), §7.3 HistoryResource, §4.3 (downloadId as join key).
- **Notes**: The M1 note "history records are written in M1" was true only across three tables (grab_history, import_history, blocklist); this change backfills the two writerless event types (`grabbed`, `download_failed`) so the feed is single-source going forward. Dedup (RISK-040): the blocked→pending retry-on-evidence loop is deliberate and untouched — only the duplicate row write is suppressed, keyed on identical event type + canonical data payload for the same downloadId.

#### Scenario: Grab-and-import cycle shares a downloadId

- **WHEN** a release is grabbed and later imports
- **THEN** `GET /api/v1/history` contains a `grabbed` row and an `imported` row sharing the same downloadId, each with nested series/issue, newest first

#### Scenario: Paged envelope with filters

- **WHEN** `GET /api/v1/history?eventType=import_blocked&seriesId=N&page=2` is requested
- **THEN** the response is the standard paging envelope filtered to that event type and series, sorted by date descending with a whitelisted sortKey (unknown keys 400)

#### Scenario: Identical blocked retries do not accrete rows

- **WHEN** a permanently blocked download is re-fed by the tracking cycle and re-blocks with a byte-identical reasons payload N times
- **THEN** exactly one `import_blocked` row exists for that outcome; a retry whose reasons/data CHANGE writes a new row

#### Scenario: Download failure is a history event

- **WHEN** a tracked download fails and is blocklisted
- **THEN** a `download_failed` history row is written carrying the downloadId and failure message

### Requirement: FRG-API-012 — Wanted/missing endpoint

The API SHALL expose a paged `GET /wanted/missing` listing monitored, published issues without files, derived at query time from the canonical wanted query — never from a stored wanted status. (The former cutoff-unmet half of this requirement is REMOVED: quality cutoffs are parked outside M2/M3, so plain missing is the whole surface.)

- **Milestone**: M2
- **Source**: sonarr-architecture.md §1.1 ("wanted is derived"), §7.1 Wanted/Missing; mylar-feature-surface.md §3 (Mylar's stored Wanted status — divergence).
- **Notes**: Deliberate divergence from Mylar: no stored per-issue Wanted status. Cutoff-unmet dropped per the 2026-07-06 M2 reshape (QUAL-003/004/005 parked to B; API-012 narrowed accordingly). Reuses `repo.wanted_issues` — the same SELECT the backlog search walks, so screen and search can never disagree.

#### Scenario: Derived missing list

- **WHEN** an issue is monitored, its series monitored, its release date passed, and it has no file
- **THEN** it appears in `GET /api/v1/wanted/missing` (paged envelope, nested series); importing a file removes it with no status write, deleting the file returns it

#### Scenario: No stored status, no cutoff surface

- **WHEN** the API surface is inspected
- **THEN** there is no wanted-status write path and no cutoff-unmet endpoint — the missing list is exactly the backlog search's target set

### Requirement: FRG-API-013 — Config resource endpoints

The API SHALL expose typed config resources (host, media management, naming, UI) as GET/PUT singletons so all settings changes flow through the documented API rather than ad-hoc form posts.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §7.1 Config/{host, mediamanagement, naming, ui}; mylar-feature-surface.md §7 (Mylar's 34-section ini — the anti-pattern being replaced).
- **Notes**: `api/config_resources.py` (new). This change lands `config/naming` and `config/mediamanagement`; host/ui arrive with their own reqs. Field-precise 4xx uses the existing uniform shape (`api/errors.py` `ApiError`/`error_body`) with `errors[].field` under a `settings.` prefix. No secret-typed field appears in these resources (secrets remain DEP/AUTH). Persists into `config.yaml` and re-loads `app.state.settings`. Tag test: `tests/api/test_config_resources.py`.

#### Scenario: GET returns the typed current values

- **GIVEN** a running instance
- **WHEN** `GET /api/v1/config/naming` is called
- **THEN** it returns the typed current naming values (file template, folder template, rename toggle, illegal-character policy) with no secret fields present.

#### Scenario: PUT round-trips and takes effect

- **GIVEN** a `PUT /api/v1/config/naming` changing the file template
- **WHEN** a subsequent `GET /api/v1/config/naming` runs and a rename preview is computed
- **THEN** the GET reflects the new template and the preview renders names using it.

#### Scenario: Per-field validation error in the uniform shape

- **GIVEN** a `PUT` carrying an invalid value (a blank required template, or a `recycle_bin_path` that fails confinement/writability)
- **WHEN** it is submitted
- **THEN** the response is a 400 in the `{"message", "errors":[{"field","message"}]}` shape naming the offending setting field, and no config value is changed.

#### Scenario: Media-management resource round-trips its fields

- **GIVEN** the media-management resource
- **WHEN** `PUT /api/v1/config/mediamanagement` sets transfer mode, recycle-bin path, retention days, and import mode, followed by a `GET`
- **THEN** the GET returns those values and the running settings reflect them.

#### Scenario: No secret ever transits these resources

- **GIVEN** the `config/naming` and `config/mediamanagement` schemas
- **WHEN** their fields are audited
- **THEN** no secret-typed field is present in either request or response body.

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

### Requirement: FRG-API-015 — Manual import endpoint

The API SHALL expose manual-import endpoints that list candidate files under a given path with their would-be import decisions and rejection reasons, and accept user-corrected mappings (series/issue/format overrides) for execution through the same import pipeline as automatic imports.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §5.5 ManualImportService, §7.1 ManualImport.
- **Notes**: Resolution path for ImportBlocked queue items; pairs with the UI overlay. Listing is read-only (no disk mutation beyond inspection); execution enqueues a pp-pool command that drives `import_candidate`. Same envelope/`ApiError` conventions as the rest of the API.

#### Scenario: List candidates for a path with decisions and reasons

- **WHEN** `GET /api/v1/manual-import?path=<abs>` is called for a folder of archives
- **THEN** it returns one entry per candidate with its resolved `approved` verdict, verbatim `rejections`, suggested series/issue/format, and embedded-metadata summary (`comicInfoPresent`, `cvIssueId`, `verified`) — computed via `aggregate → build_evaluation → decide`, touching no disk beyond inspection.

#### Scenario: List candidates for a blocked download

- **WHEN** `GET /api/v1/manual-import?downloadId=<id>` is called for an `import_blocked` download
- **THEN** it reuses the completed-download intake (remote-path mapping + grab hints) and lists that download's files with their would-be decisions and reasons.

#### Scenario: Submit corrected mappings for execution

- **WHEN** `POST /api/v1/manual-import` is sent `{ files: [{ path, seriesId, issueId, format? }] }`
- **THEN** the overrides are validated and a `manual-import` command is enqueued on the pp-pool, returning `201` with a `CommandResource`; on completion the files that resolved import and the rest report their blocking reasons — the same pipeline and history as automatic import.

#### Scenario: Unreadable path or unknown download is a typed error

- **WHEN** the path cannot be resolved/read or the `downloadId` is unknown
- **THEN** the endpoint returns a typed `ApiError` (400/404) rather than a crash or an empty success.

#### Scenario: Override cannot force a rejected file past the safety specs

- **WHEN** a submitted mapping targets a corrupt archive or a below-floor/no-space file
- **THEN** execution still runs the full decision set and the file is reported blocked/failed with its reason — the API exposes no "force" that skips `ArchiveValidSpec`/`FreeSpaceSpec`/`JunkFilterSpec`.

### Requirement: FRG-API-016 — Parse debug endpoint

The API SHALL expose `GET /parse?title=` returning the parsed issue info (series title, issue number, year, format, group) and the library mapping result for an arbitrary release title.

- **Milestone**: B
- **Source**: sonarr-architecture.md §7.1 (Parse debug endpoint), §2.5 release parsing.
- **Notes**: Pure developer/support convenience; trivially thin over the parser (SRCH area). Keep last so numbering leaves fundamentals first.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Posting a known-ambiguous release title returns the parser's structured interpretation without side effects.

### Requirement: FRG-API-017 — ComicVine suggest (bounded lookup variant)

The API SHALL expose `GET /series/lookup/suggest?term=` returning a bounded set of ComicVine volume candidates (first page only, approximately ten results) for as-you-type suggestion, performing at most ONE upstream ComicVine page request per call and NEVER the full pagination walk that `GET /series/lookup` performs. The suggest response envelope SHALL carry `records` and a `complete` flag (distinguishing a clean single-page fetch from one degraded by a mid-fetch upstream failure) but SHALL NOT carry a `truncated` flag, because a suggest result is definitionally partial (the full lookup remains the complete search). The endpoint SHALL neutralise ComicVine filter metacharacters on `term` exactly as the full lookup does, and SHALL honour the SAME upstream-error contract as `GET /series/lookup`: a ComicVine authentication failure yields HTTP 503 with a message identifying the ComicVine credential and an `errors` entry with `field="comicvine_api_key"` as the machine-readable discriminator — never a `200` with an empty list — and neither the response nor any log line contains the API key value.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §7.1 (Series lookup / add flow, as-you-type suggestion); m2-lookup-error-surfacing (the `comicvine_api_key` field discriminator and 503 contract); FRG-API-003 (the full lookup this bounds), FRG-META-003/004 (rate limiting + bounded pagination).
- **Notes**: A cheap accelerator over FRG-API-003's full lookup, not a replacement — it exists to back FRG-UI-005's debounced autosuggest. Reuses the existing outbound ComicVine integration (`ComicVineClient`) with a new single-page `suggest_series` fetch; reuses the full lookup route's auth/error mapping code (not a parallel copy) so `isComicVineAuthError` on the client keeps working unchanged. `have_it` annotation over the ≤10 returned ids is retained for parity with the full lookup; plausibility scoring MAY be omitted to keep the call cheap. Security (FRG-PROC-006): a new query-string endpoint designed to be called frequently as the user types raises an outbound request-amplification consideration, bounded by client ≥3-char + debounce gating (FRG-UI-005), the single-page server fetch, and the existing CV rate limiter — recorded as a `docs/security/` delta in this change.

#### Scenario: Suggest returns a bounded first page without walking

- **WHEN** `GET /api/v1/series/lookup/suggest?term=batman` is called
- **THEN** the response is a `{records, complete}` envelope of at most ~10 ComicVine candidates from the first page only, and the client issues at most one upstream ComicVine page request for the call (no multi-page walk), each candidate carrying at least cv_volume_id, name, start year, publisher, issue count, image url, and a `have_it` flag for already-owned volumes

#### Scenario: Suggest has no truncated flag; partiality is expected

- **WHEN** the suggest response is inspected
- **THEN** it carries a `complete` flag but NO `truncated` flag — a clean single-page fetch is `complete=true`, a fetch degraded by a mid-fetch upstream failure is `complete=false`, and there is no cap-was-hit signal because more results always live behind the full `GET /series/lookup`

#### Scenario: Suggest surfaces a ComicVine auth failure identically to lookup

- **WHEN** `GET /api/v1/series/lookup/suggest?term=` is called and ComicVine rejects the request as unauthorized (missing, empty, or invalid API key)
- **THEN** the endpoint returns HTTP 503 with a message identifying the ComicVine credential and an `errors` entry with `field="comicvine_api_key"` — not a `200` with an empty list — matching the full lookup contract exactly, and neither the response body nor any log line contains the API key value

#### Scenario: Suggest neutralises ComicVine filter metacharacters

- **WHEN** `term` contains ComicVine filter metacharacters (`,` or `:`)
- **THEN** they are neutralised before the upstream filter is built, exactly as the full lookup does, so the term cannot inject additional ComicVine filter fields

### Requirement: FRG-API-018 — ComicVine credential settings resource

The API SHALL expose a settings resource that lets the UI READ the ComicVine API key's configured STATUS and SOURCE, UPDATE the key, and TEST ComicVine connectivity — without the key value ever leaving the server in a response. The read SHALL return whether the key is configured and its source — `unset`, `file` (set in `config.yaml`), or `environment` (set via `FORAGERR_COMICVINE_API_KEY`) — and SHALL NEVER return the key value. An update SHALL persist a supplied key into `config.yaml` through the existing atomic documented-config writer (so the key is written as a real value, not a commented placeholder) and SHALL apply it to the running application WITHOUT a restart; a blank update SHALL keep the currently-stored value rather than clearing it. Because the `FORAGERR_COMICVINE_API_KEY` environment variable takes precedence over the config file, when the key's source is `environment` the resource SHALL report it as environment-managed and SHALL reject an update as ineffective (naming the environment variable) rather than silently persisting a shadowed value. The connectivity test SHALL exercise ComicVine with the effective key and report success or failure. In no case SHALL the key value appear in any response body or log line, and an updated key SHALL be registered with the log-redaction filter.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §4 (provider/connection settings with test); m2-first-run-defaults (the "check Settings" guidance needs a real settings-write surface); FRG-API-013 (the config-resource pattern this extends — read-modify-write-reload with `render_documented_config` + `atomic_write_text` under a write lock), FRG-META-002 (ComicVine key handling + redaction), FRG-IDX-003 (the provider connectivity-test contract this mirrors for ComicVine).
- **Notes**: FRG-API-013's existing `naming`/`mediamanagement` resources deliberately carry no secret fields, so this is a NEW resource, not a modification of them. Persistence reuses `render_documented_config`, which already writes a supplied secret uncommented — no separate secrets store is introduced. Live-apply is the existing `app.state.settings` swap: the ComicVine client is constructed per request and reads the key fresh, so the swap suffices with no client-recreation plumbing. Source detection reads `os.environ["FORAGERR_COMICVINE_API_KEY"]` directly — the one place that must distinguish env from file, because the effective `Settings` object collapses both sources. Security (FRG-PROC-006): a new state-changing endpoint that accepts a secret from the (tailnet-only, unauthenticated — RISK-020) UI and persists it in plaintext (RISK-013, at-rest encryption is M5/FRG-AUTH-008); mitigations are write-only-over-the-API (GET never returns the value) + log redaction on write — recorded as a `docs/security/` delta in this change.

#### Scenario: Read reports configured status and source, never the value

- **WHEN** the ComicVine credential settings resource is read
- **THEN** the response reports whether the key is configured and its source (`unset`, `file`, or `environment`) and does NOT contain the key value or any substring of it

#### Scenario: Update persists the key and applies it without a restart

- **WHEN** a non-blank ComicVine API key is submitted to the resource and no `FORAGERR_COMICVINE_API_KEY` environment variable is set
- **THEN** the key is written into `config.yaml` as a real value via the atomic documented-config writer, the running application uses the new key on the next ComicVine request without a restart, the response does not echo the key, and the new value is registered with the log-redaction filter

#### Scenario: A blank update keeps the stored key

- **WHEN** the resource receives an update with a blank ComicVine API key
- **THEN** the currently-stored key is retained (not cleared), matching the write-only "leave blank to keep" convention used by provider secret fields

#### Scenario: An environment-supplied key is reported read-only and not shadowed

- **WHEN** `FORAGERR_COMICVINE_API_KEY` is set and an update is submitted to the resource
- **THEN** the read reports `source="environment"`, and the update is rejected as environment-managed (naming the environment variable) rather than persisting a value the environment would shadow

#### Scenario: Connectivity test uses the effective key without leaking it

- **WHEN** the connectivity-test action is invoked
- **THEN** it exercises ComicVine with the effective key and returns a success or failure result, and neither the response nor any log line contains the key value

#### Scenario: The key value never appears in a response or log

- **WHEN** any of the resource's read, update, or test actions runs
- **THEN** no response body and no emitted log line contains the ComicVine API key value

### Requirement: FRG-API-019 — Pull/weekly resource endpoint

The API SHALL expose `GET /api/v1/pull?week=<iso-week>` returning the
metadata-derived weekly release projection (FRG-PULL-001) for the requested
store-date week, defaulting to the current week when `week` is omitted. The
response SHALL use the standard paging envelope (FRG-API-006) and standard
resource/error conventions (FRG-API-002), each row carrying the pull entry's
descriptive fields (publisher, series name, issue number, release date, any
source-supplied ComicVine IDs), its `match_type`
(`id` / `name_seq` / `unmatched` / `new_series`), the linked library issue id when
matched, and — for a linked entry — the matched issue's **derived state**
(missing/wanted, downloading, downloaded, or unmonitored) computed from issue and
queue records (FRG-SER-004 / FRG-DL-008), or a pending-refresh indication for a
matched-but-not-yet-created issue. The endpoint SHALL NOT expose any secret
(provider keys, credentials, the raw source URL's query auth if any). Manual pull
refresh is NOT a new endpoint — it is the existing task force-run
`POST /api/v1/system/task/pull-refresh` (FRG-API-014 / FRG-SCHED-007).

- **Milestone**: M3
- **Source**: sonarr-architecture.md §7.1 (Calendar resource); mylar-feature-surface.md
  §1 (weekly pull view); FRG-PULL-001 (the projection this exposes), FRG-API-006
  (paging envelope), FRG-API-014 (task force-run reused for manual refresh).
- **Notes**: This is the **minimal read surface** m3-pull-experience (change 2)
  builds the weekly pull screen (FRG-UI-018) and its prev/current/next navigation
  on — the endpoint accepts an arbitrary `week`, so navigation is three client calls
  with no server-side navigation state. Derived state is projected from issue +
  queue records at request time (a cheap join over the pre-matched `pull_entries`
  store), never a status held on the pull entry (D4). Per-entry actions
  (want/skip/search) in change 2 delegate to the existing issue endpoints
  (FRG-API-004 / FRG-SRCH-008) rather than to this endpoint, which is read-only.

#### Scenario: Weekly resource returns the projection for a given week

- **WHEN** `GET /api/v1/pull?week=2026-W27` is requested
- **THEN** the response is a standard paging envelope whose rows are that week's
  pull entries, each carrying its descriptive fields, `match_type`, the linked
  issue id when matched, and — for linked entries — the matched issue's derived
  state, and it contains no provider key or credential value

#### Scenario: Omitted week defaults to the current week

- **WHEN** `GET /api/v1/pull` is requested with no `week` parameter
- **THEN** the response is the projection for the current store-date week, so the
  screen's default load needs no week computation client-side

#### Scenario: Read endpoint writes nothing; refresh is the task force-run

- **WHEN** the pull resource endpoint is exercised
- **THEN** it only reads (no issue status is mutated by `GET /pull`), and the only
  way to refresh pull data via the API is the existing
  `POST /api/v1/system/task/pull-refresh` task force-run — there is no separate
  pull-refresh endpoint

### Requirement: FRG-API-020 — Series grouping projection

The API SHALL expose a read projection of franchise groups for the grouped library
view: `GET /api/v1/series/groups` returning each franchise group with its member
series and an **aggregated** roll-up (member/series count, total and owned issue
counts) computed in a bounded way that does NOT multiply the existing per-series
statistics N+1 (a single aggregate query, not per-series stats per group). The
response SHALL use the standard paging envelope and conventions (FRG-API-006/002),
expose no secret, and be read-only. The existing flat `GET /api/v1/series` list SHALL
be unchanged except that each `SeriesResource` gains its `series_group_id` (nullable),
so a client can render a group affordance in the flat view without a second call.

#### Scenario: Grouped projection returns franchises with aggregated stats

- **WHEN** `GET /api/v1/series/groups` is called with three series across two franchises
- **THEN** it returns two groups, each listing its member series and an aggregated issue/owned roll-up, in the standard paging envelope, with no secret exposed

#### Scenario: Flat list carries the group id

- **WHEN** `GET /api/v1/series` is called
- **THEN** each series resource includes its `series_group_id` (or null), and the flat list's shape, sorting, and paging are otherwise unchanged

#### Scenario: Aggregation is bounded

- **WHEN** the grouping projection computes roll-up stats
- **THEN** it does so with a bounded aggregate query rather than the per-series statistics path multiplied per group (no N+1 explosion)

