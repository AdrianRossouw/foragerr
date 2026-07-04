# meta Spec Delta

## ADDED Requirements


### Requirement: FRG-META-001 — ComicVine client fundamentals

The system SHALL access ComicVine exclusively through a single client module that requests JSON responses with explicit field lists, applies connect and read timeouts to every request, verifies TLS by default, and sends an honest configurable User-Agent.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §1.1 (XML/minidom weakness), §3.4, §4 (no timeout, expat risk), §5.
- **Notes**: Deliberate divergences from Mylar: JSON not XML/minidom; timeouts mandatory; no global TLS-off knob (if a verify override ever exists it is per-host, default on, and flagged in `docs/security/`); no spoofed Chrome UA.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** No ComicVine request in the codebase lacks a timeout or requests XML; a hung-connection test fails the request within the configured timeout instead of blocking.

### Requirement: FRG-META-002 — API key handling

The system SHALL read the ComicVine API key from environment/`.env` configuration, transmit it as a request parameter that is scrubbed from all log output, and SHALL never write the key to logs, error messages, diagnostics, or persisted files.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §1.2, §4 (key-in-URL leak), §5; CLAUDE.md Secrets.
- **Notes**: Requests will still carry `api_key` as a query parameter (ComicVine requires it); the requirement is that foragerr's own logging/telemetry redacts it. Security-relevant: update STRIDE/risk register in the same change (FRG-PROC-006).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A log capture of a full add-series flow at debug level contains no substring of the configured key.

### Requirement: FRG-META-003 — Client-side rate limiting with 429 handling

The system SHALL enforce a shared client-side ComicVine rate limit (token bucket or equivalent, default ≤1 request per 2 seconds, configurable) across all concurrent operations, and on HTTP 420/429 or a detected ban response SHALL back off honoring Retry-After when present (exponential otherwise), mark the ComicVine health status degraded, and resume automatically after the backoff.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §1.3, §3.1 (fixed sleep, no 429 handling, unlocked concurrency), §5; sonarr-architecture.md §2.6 (rate-limit responses fast-forward back-off).
- **Notes**: D3 — replaces Mylar's blind per-call sleep. The limiter must be process-global (Mylar's `mb_lock` is never acquired). Ban-page detection (Abnormal Traffic) kept as a fallback signal.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Two concurrent refresh operations never exceed the configured request rate (verified by client-side request timestamps); a simulated 429 with Retry-After delays the next request accordingly and surfaces a degraded health status.

### Requirement: FRG-META-004 — Pagination with partial-failure tolerance

The system SHALL page through ComicVine list responses (100 per page, offset-based) until `number_of_total_results` is satisfied, and on a mid-pagination failure SHALL persist the pages already retrieved, record the sync as incomplete, and schedule a retry rather than discarding partial results or reporting success.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §1.4, §5.
- **Notes**: Divergence: Mylar returns partial results silently; foragerr records incompleteness so refresh reconciliation does not delete issues it merely failed to fetch (interacts with the reconciliation requirement below).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A simulated failure on page 3 of 5 leaves pages 1–2 persisted, the series flagged incomplete, and a retry queued; batched ID lookups chunk at ≤100 IDs per request.

### Requirement: FRG-META-005 — Volume-to-series mapping

The system SHALL map a ComicVine volume response to a series record — name, publisher, imprint, start year, issue count, aliases, description, site URL, first-issue reference, and cover image URLs — as typed nullable values, never persisting sentinel strings such as `'None'`, `'Unknown'`, or `'0000'`.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §1.5, §3.7 (silent degradation), §5.
- **Notes**: When ComicVine's `count_of_issues` disagrees with returned issue elements, the actual element count wins (Mylar behavior worth keeping). Missing start year is backfilled from the first issue's cover date (one extra targeted call).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A volume with missing publisher and year stores NULLs; no `'None'` string appears in any series column after importing a fixture set of malformed responses.

### Requirement: FRG-META-006 — Issue mapping

The system SHALL map each ComicVine issue to an issue record — issue ID, number, title, cover date, store date, image URLs — preserving non-integer issue numbers verbatim alongside a computed sort key, defaulting missing dates to NULL, and SHALL surface (not silently skip) issues lacking an issue number.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §1.5 (GetIssuesInfo; unnumbered issues skipped); sonarr-architecture.md §1.1 (decimal/string issue numbers).
- **Notes**: Divergence: Mylar silently drops unnumbered issues; foragerr records them unmonitored with a warning so have/total counts remain honest. Mylar's digital-date prose heuristic is dropped (unreliable; store date suffices).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A fixture volume containing `1`, `1.5`, `½`, an unnumbered issue, and a missing store date imports with correct sort order, NULL date, and one visible "unnumbered issue" warning.

### Requirement: FRG-META-007 — Series search

The system SHALL provide a ComicVine series search by name (volumes endpoint with per-word name filters) that paginates to a bounded result count and annotates each candidate with plausibility signals — publication-year range, issue-count sanity for a target issue when given, already-in-library flag — and SHALL exclude publishers on a configurable ignore list.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §1.6 (findComic heuristics), §5; mylar-feature-surface.md capability map META (ignored-publishers).
- **Notes**: Keep Mylar's plausibility *annotations* but let the user (and the add flow) make the final choice — filters prune ranking, they do not hard-drop except the publisher ignore list. Result cap ~1000 with a visible truncation warning.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Searching a known title returns candidates with year/count annotations and `haveit` set for a series already in the library; an ignored-publisher volume is absent.

### Requirement: FRG-META-008 — Refresh reconciliation (Sonarr model)

On every series metadata refresh the system SHALL re-fetch the volume and its issues and reconcile against local records by ComicVine issue ID: insert new issues (monitored per the series' monitor-new-items policy), update changed fields on matched issues, and delete local issue records absent from the source — except that no deletions occur when the fetch was partial/incomplete.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §1.2 step 3 (RefreshEpisodeService), §8; mylar-feature-surface.md §8 (series metadata refresh).
- **Notes**: Deliberate divergence from Mylar (which upserts but never reconciles deletions). Deleting an issue that has a file keeps the file record orphan-visible for manual review rather than deleting files. Refresh is triggered by add, manually, by schedule (below), and by PULL when a pulled issue is missing.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A refresh against a fixture where one issue was added, one renamed, and one removed yields exactly one insert, one field update, one delete; the same fixture with a simulated partial fetch performs no deletes.

### Requirement: FRG-META-009 — Scheduled refresh with staleness rules

The system SHALL run scheduled metadata refresh on a configurable interval (default ~12 h) with per-series skip logic: skip series synced recently (default <6 h), always refresh series stale beyond a maximum (default >30 days), and refresh ended series only when recently active — with per-series and global force-refresh commands that bypass the skip rules.

- **Milestone**: B
- **Source**: sonarr-architecture.md §1.2 (ShouldRefreshSeries, 12 h cadence); mylar-feature-surface.md §8 (REFRESH_CACHE, DB Updater).
- **Notes**: M1 gets on-add and manual refresh only (previous requirement); the scheduler belongs with the SCHED backbone. Thresholds configurable.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A scheduler pass over fixtures (fresh, stale, ended-old, ended-recent) refreshes exactly the required subset; force-refresh refreshes an otherwise-skipped series.

### Requirement: FRG-META-010 — Incremental changed-since sync

The system SHALL support an incremental sync mode that queries ComicVine for issues/volumes changed since the last successful sync (date_last_updated filter, sorted ascending), converts correctly between UTC and ComicVine's US/Pacific timestamps, processes a bounded batch per run (default 1500) deferring the remainder, and refreshes only affected library series.

- **Milestone**: B
- **Source**: mylar-comicvine.md §1.1 (db_updater), §1.7, §5; mylar-feature-surface.md §8 (watchlist_updater, backfill batching).
- **Notes**: Complements (does not replace) full per-series refresh — full refresh remains the correctness backstop since the changed-feed can miss windows. Mylar's `PROBLEM_DATES` known-bad-window excision is dropped unless proven necessary.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** With a mocked changed-since feed touching 2 of 10 library series, only those 2 are refreshed; a 3000-item backlog is consumed across two runs; timestamps round-trip across a DST boundary fixture.

### Requirement: FRG-META-011 — Volume identity-change guard

On refresh, when a majority of a volume's identity fields (name, start year, publisher, site URL) change simultaneously, the system SHALL suspend the refresh for that series, flag it for manual review, and leave local data untouched instead of overwriting.

- **Milestone**: B
- **Source**: mylar-comicvine.md §1.7 (check_that_biatch), §5.
- **Notes**: Guards against ComicVine volume-ID deletion/reuse. Review resolution = user confirms (accept new identity) or re-maps the series to a different volume ID.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A fixture refresh where 3 of 4 identity fields change marks the series "needs review" and modifies no local fields; a 1-of-4 change proceeds normally.

### Requirement: FRG-META-012 — Heuristic fields with provenance and override

The system SHALL derive book type (print/digital/TPB/GN/HC/one-shot), volume number, and imprint from ComicVine description/deck text as best-effort values, persist per-field provenance (source | heuristic | user), and SHALL never let refresh overwrite a user-provenance value.

- **Milestone**: B
- **Source**: mylar-comicvine.md §1.5 (get_imprint_volume_and_booktype), §3.5, §5.
- **Notes**: Book type matters because search filtering and TPB-vs-issue disambiguation depend on it. Foragerr should port the *classification outcomes*, not Mylar's accreted negative-phrase lists verbatim; keep the test corpus honest about misfires. TPB contents-list scraping (BeautifulSoup over description links) is B-of-B: exclude initially, revisit if TPB handling needs it.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A heuristic book type displays as such in the API payload; setting it manually flips provenance to user and survives a forced refresh; the one-shot forcing rule (single issue, past year, not TPB/HC/GN) is applied.

### Requirement: FRG-META-013 — Cover art download and cache

The system SHALL download series and issue cover images referenced by ComicVine into a local cache, serve UI/OPDS artwork exclusively from that cache, refresh images older than a configurable age (default 30 days) lazily, and clean up orphaned cached images.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §1.7 (cover cache); mylar-feature-surface.md §8 (cache.py, 30-day freshness) and capability map META.
- **Notes**: UI browse and OPDS in the M1 slice need covers. Cover *regeneration* API and alternate-cover selection are B refinements folded here as Notes, not separate requirements.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** After adding a series, its cover renders from a local URL with no browser request to comicvine.gamespot.com; deleting the series removes its cached artwork on the next cleanup pass.

### Requirement: FRG-META-014 — ComicVine content is untrusted input

The system SHALL treat all ComicVine-originated strings (names, aliases, descriptions, image URLs) as untrusted: strip/sanitize HTML on ingest, encode on output, and never interpolate them into shell commands, SQL, or filesystem paths without sanitization through the central path/query builders.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §4 (user-editable wiki content → XSS/steering), §5.
- **Notes**: Security-relevant — new parser of untrusted input; STRIDE/risk-register update required in the same change (FRG-PROC-006). Also constrains search: ComicVine-derived text steers indexer/DDL queries, so query construction must go through the same sanitization.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A series whose ComicVine description contains a script tag and whose title contains path separators and quotes imports safely: the UI renders inert text and the created folder name is sanitized.
