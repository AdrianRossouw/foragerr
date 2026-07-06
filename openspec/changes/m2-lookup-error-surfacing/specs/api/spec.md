# api — delta for m2-lookup-error-surfacing

## MODIFIED Requirements

### Requirement: FRG-API-003 — Series resources with ComicVine lookup

The API SHALL provide series endpoints: `GET /series` (library index), `GET/POST/PUT/DELETE /series/{id}`, and `GET /series/lookup?term=` performing a live ComicVine volume search returning candidate series with remote poster, year, publisher, and external id; POST accepts add options (root folder, monitoring strategy, format profile) as write-only fields. Lookup SHALL distinguish outcome classes: a ComicVine authentication failure yields a structured error response (not an empty 200), and a successful-but-degraded walk is marked incomplete in the response envelope so callers can tell it apart from a clean empty result.

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
- **THEN** the endpoint returns a structured upstream-error response (502-class, message identifying the ComicVine credential as the cause) rather than `200` with an empty list, and neither the response nor the log line contains the API key value

#### Scenario: Lookup exposes walk completeness distinctly from clean-empty

- **WHEN** the lookup's pagination walk degrades on a non-auth failure and returns partial candidates with `complete=False`
- **THEN** the response envelope marks the result incomplete so the client can distinguish it from a complete walk that genuinely matched nothing (which stays a `200` complete-and-empty response)

#### Scenario: POST validates and returns the queued refresh command id

- **WHEN** a valid `POST /api/v1/series` supplies a ComicVine volume, root folder, monitoring strategy, and format profile as write-only add options
- **THEN** the response creates the series and includes the command id of the queued refresh; an invalid volume, missing/invalid root folder, or a duplicate of an existing series is rejected with a structured 400 naming the offending field

#### Scenario: DELETE removes the row only; file deletion is not yet supported

- **WHEN** `DELETE /api/v1/series/{id}` is called
- **THEN** the series row is removed without touching files, and `DELETE /api/v1/series/{id}?deleteFiles=true` returns 501 (not implemented in M1) rather than silently ignoring the flag
