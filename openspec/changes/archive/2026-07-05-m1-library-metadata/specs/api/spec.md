## MODIFIED Requirements

### Requirement: FRG-API-003 — Series resources with ComicVine lookup

The API SHALL provide series endpoints: `GET /series` (library index), `GET/POST/PUT/DELETE /series/{id}`, and `GET /series/lookup?term=` performing a live ComicVine volume search returning candidate series with remote poster, year, publisher, and external id; POST accepts add options (root folder, monitoring strategy, format profile) as write-only fields.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.1 (Series + lookup), §7.3 SeriesResource shape, §1.2 add flow.
- **Notes**: Series add *behavior* (refresh chain, monitoring) is SER/META area; this requirement owns only the HTTP surface. Dedup hint: statistics aggregation mirrors Sonarr `SeriesStats/`.

#### Scenario: Series index returns a paged envelope with whitelisted sort

- **WHEN** `GET /api/v1/series?page=1&pageSize=20&sortKey=title` is requested
- **THEN** the response is the paging envelope with `totalRecords` and `records[]`, and an unrecognized `sortKey` yields a 400 rather than a silent default or 500

#### Scenario: Lookup annotates ComicVine candidates without auto-adding

- **WHEN** `GET /api/v1/series/lookup?term=` is called with a title term
- **THEN** the response lists ComicVine candidates with remote poster, year, publisher, and external id plus plausibility annotations, and no library series row is created as a side effect

#### Scenario: POST validates and returns the queued refresh command id

- **WHEN** a valid `POST /api/v1/series` supplies a ComicVine volume, root folder, monitoring strategy, and format profile as write-only add options
- **THEN** the response creates the series and includes the command id of the queued refresh; an invalid volume, missing/invalid root folder, or a duplicate of an existing series is rejected with a structured 400 naming the offending field

#### Scenario: DELETE removes the row only; file deletion is not yet supported

- **WHEN** `DELETE /api/v1/series/{id}` is called
- **THEN** the series row is removed without touching files, and `DELETE /api/v1/series/{id}?deleteFiles=true` returns 501 (not implemented in M1) rather than silently ignoring the flag

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
