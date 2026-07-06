# api — delta for m2-lookup-error-surfacing

## MODIFIED Requirements

### Requirement: FRG-API-003 — Series resources with ComicVine lookup

The API SHALL provide series endpoints: `GET /series` (library index), `GET/POST/PUT/DELETE /series/{id}`, and `GET /series/lookup?term=` performing a live ComicVine volume search returning candidate series with remote poster, year, publisher, and external id; POST accepts add options (root folder, monitoring strategy, format profile) as write-only fields. Lookup SHALL distinguish outcome classes: a ComicVine authentication failure yields a structured error response (not an empty 200) carrying a machine-readable field discriminator so clients never classify by message prose, and the response envelope marks a degraded walk (`complete`) and a deliberately capped walk (`truncated`) as distinct conditions, both distinguishable from a clean empty result.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.1 (Series + lookup), §7.3 SeriesResource shape, §1.2 add flow.
- **Notes**: Series add *behavior* (refresh chain, monitoring) is SER/META area; this requirement owns only the HTTP surface. Dedup hint: statistics aggregation mirrors Sonarr `SeriesStats/`. Outcome-class distinction added in m2-lookup-error-surfacing (a missing/invalid key previously surfaced as `200 []`).

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

#### Scenario: DELETE removes the row only; file deletion is not yet supported

- **WHEN** `DELETE /api/v1/series/{id}` is called
- **THEN** the series row is removed without touching files, and `DELETE /api/v1/series/{id}?deleteFiles=true` returns 501 (not implemented in M1) rather than silently ignoring the flag
