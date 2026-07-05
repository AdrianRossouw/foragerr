# META — Metadata (ComicVine) Specification

## Purpose

Baseline requirements for metadata (comicvine), mined from the
Phase 1 reference research (`docs/research/`). Baseline depth per the Phase 2 scope
decision: SHALL + coarse acceptance; scenario-level elaboration happens in the
milestone change that implements each requirement (FRG-PROC-003, FRG-PROC-009).

## Requirements

### Requirement: FRG-META-001 — ComicVine client fundamentals

The system SHALL access ComicVine exclusively through a single client module that requests JSON responses with explicit field lists, applies connect and read timeouts to every request, verifies TLS by default, and sends an honest configurable User-Agent.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §1.1 (XML/minidom weakness), §3.4, §4 (no timeout, expat risk), §5.
- **Notes**: Deliberate divergences from Mylar: JSON not XML/minidom; timeouts mandatory; no global TLS-off knob (if a verify override ever exists it is per-host, default on, and flagged in `docs/security/`); no spoofed Chrome UA.

#### Scenario: Every request goes through the typed client on the shared outbound factory

- **WHEN** any ComicVine operation issues a request
- **THEN** it is built by the single typed client on the shared outbound HTTP factory (`external` profile), targets base `comicvine.gamespot.com/api`, carries `format=json` and a per-endpoint `field_list`, sends User-Agent `foragerr/<version>`, and inherits the factory's connect/read timeouts, TLS verification, SSRF policy, and response byte cap — no ComicVine call bypasses the client or requests XML.

#### Scenario: Hung connection fails within the configured timeout

- **WHEN** a fixture server accepts the connection but never responds
- **THEN** the request fails with a typed `unavailable` exception within the configured read timeout rather than blocking the caller indefinitely.

#### Scenario: Distinct upstream conditions raise distinct typed exceptions

- **WHEN** the fixture server returns, respectively, a 401/authentication error, a 429/rate-limit response, a malformed/non-JSON body, and a 5xx/unreachable condition
- **THEN** the client raises the corresponding typed exception (auth, rate-limit, malformed, unavailable) — never a bare transport error or a silent `None`.

#### Scenario: Env-gated live smoke confirms the real endpoint contract

- **WHEN** the live-smoke suite runs with credentials supplied via environment (skipped otherwise)
- **THEN** a real `format=json` volume fetch against `comicvine.gamespot.com/api` succeeds through the typed client and returns a parseable response honoring the requested `field_list`.

### Requirement: FRG-META-002 — API key handling

The system SHALL read the ComicVine API key from environment/`.env` configuration, transmit it as a request parameter that is scrubbed from all log output, and SHALL never write the key to logs, error messages, diagnostics, or persisted files.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §1.2, §4 (key-in-URL leak), §5; CLAUDE.md Secrets.
- **Notes**: Requests will still carry `api_key` as a query parameter (ComicVine requires it); the requirement is that foragerr's own logging/telemetry redacts it. Security-relevant: update STRIDE/risk register in the same change (FRG-PROC-006).

#### Scenario: Key is a SecretStr auto-registered with the redaction filter

- **WHEN** the ComicVine API key setting is loaded
- **THEN** it is held as a `SecretStr` and its value is auto-registered with the log redaction filter, so no configuration dump, diagnostic, or persisted file contains the plaintext key.

#### Scenario: Full add-series flow at debug level never emits the key

- **WHEN** a complete add-series flow (search, volume fetch, issue pagination, cover fetch) runs at debug log level with logs captured
- **THEN** no captured line contains any substring of the configured key, even though each request carried `api_key` as a query parameter.

#### Scenario: Key is masked inside exception tracebacks

- **WHEN** a request whose URL/params include the `api_key` parameter raises and its traceback is logged
- **THEN** the factory masks the api_key-shaped parameter and the emitted traceback shows a redaction placeholder in place of the key value.

### Requirement: FRG-META-003 — Client-side rate limiting with 429 handling

The system SHALL enforce a shared client-side ComicVine rate limit (token bucket or equivalent, default ≤1 request per 2 seconds, configurable) across all concurrent operations, and on HTTP 420/429 or a detected ban response SHALL back off honoring Retry-After when present (exponential otherwise), mark the ComicVine health status degraded, and resume automatically after the backoff.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §1.3, §3.1 (fixed sleep, no 429 handling, unlocked concurrency), §5; sonarr-architecture.md §2.6 (rate-limit responses fast-forward back-off).
- **Notes**: D3 — replaces Mylar's blind per-call sleep. The limiter must be process-global (Mylar's `mb_lock` is never acquired). Ban-page detection (Abnormal Traffic) kept as a fallback signal.

#### Scenario: One process-global gate serializes all CV traffic including covers

- **WHEN** multiple concurrent callers (a series refresh, a search, and a cover fetch) issue ComicVine requests at once
- **THEN** all requests pass through the single process-global asyncio rate gate, and the observed inter-request wire times never fall below the configured minimum interval (default 2s) — concurrent callers serialize rather than bursting.

#### Scenario: Min-interval is configurable and clamped

- **WHEN** the min-interval setting is configured, including a value below the enforced floor
- **THEN** the limiter applies the configured interval when valid and clamps out-of-range values to the enforced bounds rather than accepting an unsafe rate.

#### Scenario: 429 with Retry-After backs off and flips the degraded flag

- **WHEN** the fixture server returns HTTP 429 with a `Retry-After` header
- **THEN** the client sleeps `max(retry_after, backoff)` before the next request, sets the degraded flag surfaced in the health payload, and resumes automatically once the backoff elapses.

#### Scenario: Ban page detected as a fallback signal

- **WHEN** a response body matches the Abnormal-Traffic ban page rather than carrying a 420/429 status
- **THEN** the client treats it as a rate-limit condition — backs off and marks health degraded — instead of parsing it as valid data.

### Requirement: FRG-META-004 — Pagination with partial-failure tolerance

The system SHALL page through ComicVine list responses (100 per page, offset-based) until `number_of_total_results` is satisfied, and on a mid-pagination failure SHALL persist the pages already retrieved, record the sync as incomplete, and schedule a retry rather than discarding partial results or reporting success.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §1.4, §5.
- **Notes**: Divergence: Mylar returns partial results silently; foragerr records incompleteness so refresh reconciliation does not delete issues it merely failed to fetch (interacts with the reconciliation requirement below).

#### Scenario: Offset walk cross-checked against total result count

- **WHEN** a list endpoint reports `number_of_total_results` spanning several pages
- **THEN** the client walks offsets 100 at a time until the reported total is satisfied, and the assembled result count is cross-checked against `number_of_total_results`.

#### Scenario: Mid-walk page failure returns partial results with complete=False

- **WHEN** page 3 of 5 fails after pages 1–2 were retrieved
- **THEN** the client returns the pages already retrieved with `complete=False` so the caller sees the incompleteness flag — it does not discard the partial results or report success.

#### Scenario: Hard page cap from settings bounds the walk

- **WHEN** the total advertised results would exceed the configured hard page cap
- **THEN** the walk stops at the cap and surfaces a bounded/truncated result to the caller rather than paging unboundedly.

### Requirement: FRG-META-005 — Volume-to-series mapping

The system SHALL map a ComicVine volume response to a series record — name, publisher, imprint, start year, issue count, aliases, description, site URL, first-issue reference, and cover image URLs — as typed nullable values, never persisting sentinel strings such as `'None'`, `'Unknown'`, or `'0000'`.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §1.5, §3.7 (silent degradation), §5.
- **Notes**: When ComicVine's `count_of_issues` disagrees with returned issue elements, the actual element count wins (Mylar behavior worth keeping). Missing start year is backfilled from the first issue's cover date (one extra targeted call).

#### Scenario: Absent fields map to None, never sentinel strings

- **WHEN** a recorded volume response omits publisher and start year
- **THEN** the mapped series record stores typed `None` for those fields, and no `'None'`, `'Unknown'`, `'0000'`, or `'0000-00-00'` sentinel string appears in any series column after importing a fixture set of malformed responses.

#### Scenario: Actual issue-element count overrides count_of_issues

- **WHEN** a volume's `count_of_issues` disagrees with the number of issue elements returned
- **THEN** the mapped issue count reflects the actual element count.

#### Scenario: Fields map into typed dataclasses

- **WHEN** a well-formed volume response is mapped
- **THEN** name, publisher, imprint, start year, issue count, aliases, description, site URL, first-issue reference, and cover image URLs populate a typed dataclass with each field carrying its declared type or `None`.

### Requirement: FRG-META-006 — Issue mapping

The system SHALL map each ComicVine issue to an issue record — issue ID, number, title, cover date, store date, image URLs — preserving non-integer issue numbers verbatim alongside a computed sort key, defaulting missing dates to NULL, and SHALL surface (not silently skip) issues lacking an issue number.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §1.5 (GetIssuesInfo; unnumbered issues skipped); sonarr-architecture.md §1.1 (decimal/string issue numbers).
- **Notes**: Divergence: Mylar silently drops unnumbered issues; foragerr records them unmonitored with a warning so have/total counts remain honest. Mylar's digital-date prose heuristic is dropped (unreliable; store date suffices).

#### Scenario: Non-integer issue numbers preserved verbatim as TEXT with a sort key

- **WHEN** a fixture volume contains issues `1`, `1.5`, `1.MU`, and `½`
- **THEN** each issue number is stored verbatim as TEXT (not coerced to a number) alongside a computed sort key that orders them correctly.

#### Scenario: Missing dates map to NULL, not a date sentinel

- **WHEN** an issue omits its store date
- **THEN** the mapped store date is NULL — never `'0000-00-00'` or any sentinel string.

#### Scenario: Unnumbered issue is surfaced, not dropped

- **WHEN** a fixture volume includes an issue lacking an issue number
- **THEN** the issue is recorded (unmonitored) with exactly one visible "unnumbered issue" warning rather than being silently skipped, keeping have/total counts honest.

### Requirement: FRG-META-007 — Series search

The system SHALL provide a ComicVine series search by name (volumes endpoint with per-word name filters) that paginates to a bounded result count and annotates each candidate with plausibility signals — publication-year range, issue-count sanity for a target issue when given, already-in-library flag — and SHALL exclude publishers on a configurable ignore list.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §1.6 (findComic heuristics), §5; mylar-feature-surface.md capability map META (ignored-publishers).
- **Notes**: Keep Mylar's plausibility *annotations* but let the user (and the add flow) make the final choice — filters prune ranking, they do not hard-drop except the publisher ignore list. Result cap ~1000 with a visible truncation warning.

#### Scenario: Candidates annotated with plausibility signals, no auto-pick

- **WHEN** a known title is searched
- **THEN** each returned candidate carries plausibility annotations — similarity on the shared matching key, publication-year proximity, issue-count sanity for a target issue when supplied, and an already-in-library (`haveit`) flag for a series already present — and the search returns the annotated candidate list without auto-selecting one.

#### Scenario: Ignored-publisher volumes excluded

- **WHEN** the results include a volume whose publisher is on the configurable ignore list
- **THEN** that volume is absent from the returned candidates while other plausibility signals only annotate (do not hard-drop) the remaining candidates.

#### Scenario: Bounded result count with truncation warning

- **WHEN** a search would exceed the bounded result cap
- **THEN** the results are truncated to the cap and a visible truncation warning accompanies them.

### Requirement: FRG-META-008 — Refresh reconciliation (Sonarr model)

On every series metadata refresh the system SHALL re-fetch the volume and its issues and reconcile against local records by ComicVine issue ID: insert new issues (monitored per the series' monitor-new-items policy), update changed fields on matched issues, and delete local issue records absent from the source — except that no deletions occur when the fetch was partial/incomplete.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §1.2 step 3 (RefreshEpisodeService), §8; mylar-feature-surface.md §8 (series metadata refresh).
- **Notes**: Deliberate divergence from Mylar (which upserts but never reconciles deletions). Deleting an issue that has a file keeps the file record orphan-visible for manual review rather than deleting files. Refresh is triggered by add, manually, by schedule (below), and by PULL when a pulled issue is missing.

#### Scenario: Insert, update, delete keyed by cv_issue_id in one transaction

- **WHEN** a refresh runs against a fixture where one issue was added, one had a field changed, and one was removed at the source, all keyed by `cv_issue_id`
- **THEN** reconciliation performs exactly one insert (monitored per the series' monitor-new-items policy), one field update, and one delete, all within a single transaction, and emits a `SeriesRefreshed` event after commit.

#### Scenario: Partial fetch skips the delete arm

- **WHEN** the same fixture is refreshed but the issue fetch completed with `complete=False`
- **THEN** no deletions occur — the delete arm is skipped, the event is logged, and the series is marked partial; inserts and updates may still proceed.

#### Scenario: Issues with files are never hard-deleted

- **WHEN** an issue absent from the source has an associated file
- **THEN** it is not hard-deleted; the record remains orphan-visible for manual review rather than removing the file.

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

#### Scenario: Cover fetched through the limiter and egress policy, served from disk

- **WHEN** a series is added
- **THEN** its cover is downloaded through the process-global rate limiter, the egress policy, and the factory byte cap into `<config>/covers/<series_id>.jpg`, and the UI/OPDS render it from a local URL with no browser request to `comicvine.gamespot.com`.

#### Scenario: Re-fetch only when the CV image URL changes

- **WHEN** a refresh reports the same ComicVine image URL versus a changed one
- **THEN** the cached file is reused unchanged when the URL matches and re-fetched when the URL has changed.

#### Scenario: Missing cached image yields a deterministic 404

- **WHEN** artwork is requested for a series whose cached file is absent
- **THEN** the server returns a deterministic 404 from disk rather than reaching out to ComicVine at serve time.

#### Scenario: Orphaned cached images cleaned up

- **WHEN** a series is deleted and the cleanup pass runs
- **THEN** its cached artwork is removed.

### Requirement: FRG-META-014 — ComicVine content is untrusted input

The system SHALL treat all ComicVine-originated strings (names, aliases, descriptions, image URLs) as untrusted: strip/sanitize HTML on ingest, encode on output, and never interpolate them into shell commands, SQL, or filesystem paths without sanitization through the central path/query builders.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §4 (user-editable wiki content → XSS/steering), §5.
- **Notes**: Security-relevant — new parser of untrusted input; STRIDE/risk-register update required in the same change (FRG-PROC-006). Also constrains search: ComicVine-derived text steers indexer/DDL queries, so query construction must go through the same sanitization.

#### Scenario: Every CV string sanitized once at ingest

- **WHEN** a volume/issue response is mapped
- **THEN** every ComicVine-originated string passes through `sanitize_cv_text()` at ingest (HTML reduced to text, whitespace collapsed, length capped) before it is persisted, rendered, or used downstream.

#### Scenario: Script-tag description and path-separator title import safely

- **WHEN** a series whose description contains a `<script>` tag and whose title contains path separators and quotes is imported
- **THEN** the UI renders inert text and the created folder name is derived via `safe_path_component()` — no raw CV text reaches paths, queries, or logs.

#### Scenario: CV-derived text steering search goes through sanitization

- **WHEN** ComicVine-derived text is used to construct an indexer/DDL query
- **THEN** it is built through the central sanitizing query builder, so wiki-edited content cannot steer or inject into the outbound query.
