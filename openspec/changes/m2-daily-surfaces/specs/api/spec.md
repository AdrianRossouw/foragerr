# api — delta for m2-daily-surfaces

## MODIFIED Requirements

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
- **THEN** the series row is removed without touching files; with `?deleteFiles=true` every issue file is first moved to the recycle bin (or permanently deleted only when no bin is configured), each recorded as a `file_deleted` history event with `source=manual`, and only then are the rows removed — a mid-operation failure never leaves rows deleted while files were untouched
