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

The system SHALL read the ComicVine API key from environment/`.env` configuration, from the config file, OR from the settings UI (persisted to the config file), and SHALL transmit it as a request parameter that is scrubbed from all log output, and SHALL never write the key to logs, error messages, diagnostics, or persisted files in plaintext beyond the config file/database at-rest surface already accepted. A key set or changed through the settings UI SHALL take effect on subsequent ComicVine requests WITHOUT a restart, because the key is resolved from the current effective configuration per request; and the environment variable SHALL continue to take precedence over a config-file/UI-supplied value, with that precedence reported to the operator rather than silently overriding an edit.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §1.2, §4 (key-in-URL leak), §5; CLAUDE.md Secrets; m2-first-run-defaults (the key becomes UI-settable and live-applied).
- **Notes**: Requests will still carry `api_key` as a query parameter (ComicVine requires it); the requirement is that foragerr's own logging/telemetry redacts it. Security-relevant: update STRIDE/risk register in the same change (FRG-PROC-006). m2-first-run-defaults: the key may now be supplied via the settings UI (FRG-API-018) which persists it into `config.yaml` via the documented writer; because the ComicVine client is constructed per request from `app.state.settings` and reads the key fresh, swapping the settings object after a UI write applies the new key without a restart. Env precedence is unchanged (`FORAGERR_COMICVINE_API_KEY` still wins) and is surfaced by the settings resource as `source="environment"`. At-rest encryption of the persisted key remains M6 (FRG-AUTH-008, 2026-07-10 reshape).

#### Scenario: Key is a SecretStr auto-registered with the redaction filter

- **WHEN** the ComicVine API key setting is loaded
- **THEN** it is held as a `SecretStr` and its value is auto-registered with the log redaction filter, so no configuration dump, diagnostic, or persisted file contains the plaintext key.

#### Scenario: Full add-series flow at debug level never emits the key

- **WHEN** a complete add-series flow (search, volume fetch, issue pagination, cover fetch) runs at debug log level with logs captured
- **THEN** no captured line contains any substring of the configured key, even though each request carried `api_key` as a query parameter.

#### Scenario: Key is masked inside exception tracebacks

- **WHEN** a request whose URL/params include the `api_key` parameter raises and its traceback is logged
- **THEN** the factory masks the api_key-shaped parameter and the emitted traceback shows a redaction placeholder in place of the key value.

#### Scenario: A UI-supplied key takes effect without a restart

- **WHEN** the ComicVine API key is set or changed through the settings UI (and no `FORAGERR_COMICVINE_API_KEY` environment variable is set)
- **THEN** subsequent ComicVine requests use the new key without restarting the application, because the key is resolved per request from the current effective configuration

#### Scenario: Environment precedence is preserved and reported

- **WHEN** `FORAGERR_COMICVINE_API_KEY` is set in the environment
- **THEN** the environment value remains the effective ComicVine key regardless of a config-file/UI-supplied value, and that precedence is reported to the operator (source is environment-managed) rather than a UI edit silently taking effect

### Requirement: FRG-META-003 — Client-side rate limiting with 429 handling

The system SHALL enforce a shared client-side ComicVine rate limit (token bucket or equivalent, default ≤1 request per 2 seconds, configurable) across all concurrent operations, and on HTTP 420/429 or a detected ban response SHALL back off honoring Retry-After when present (exponential otherwise), mark the ComicVine health status degraded, and resume automatically after the backoff. Velocity spacing is one of two client-side politeness dimensions: the same gate SHALL also enforce the per-path hourly budget defined by FRG-META-016 before admitting a request.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §1.3, §3.1 (fixed sleep, no 429 handling, unlocked concurrency), §5; sonarr-architecture.md §2.6 (rate-limit responses fast-forward back-off).
- **Notes**: D3 — replaces Mylar's blind per-call sleep. The limiter must be process-global (Mylar's `mb_lock` is never acquired). Ban-page detection (Abnormal Traffic) kept as a fallback signal. Amended by cv-budget-caching: the gate gained the hourly per-path budget dimension (FRG-META-016 owns its behavior; this requirement pins that both dimensions share the one process-global gate).

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

#### Scenario: Both dimensions gate one request exactly once

- **WHEN** a request is admitted through the gate
- **THEN** it consumed one unit of its path's hourly budget and honored the velocity spacing in the same acquire — there is no second gate or bypass path for any ComicVine call site, covers included.

### Requirement: FRG-META-004 — Pagination with partial-failure tolerance

The system SHALL page through ComicVine list responses (100 per page, offset-based) until `number_of_total_results` is satisfied, and on a mid-pagination failure SHALL persist the pages already retrieved, record the sync as incomplete, and schedule a retry rather than discarding partial results or reporting success. Authentication failures (HTTP 401/403 or ComicVine error code 100) are exempt from this tolerance: they SHALL propagate to the caller as a typed auth error rather than degrade to a partial/empty result, because an invalid credential cannot succeed on any subsequent page.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §1.4, §5.
- **Notes**: Divergence: Mylar returns partial results silently; foragerr records incompleteness so refresh reconciliation does not delete issues it merely failed to fetch (interacts with the reconciliation requirement below). Auth carve-out added in m2-lookup-error-surfacing: swallowing `ComicVineAuthError` made a missing/invalid API key indistinguishable from an empty search result.

#### Scenario: Offset walk cross-checked against total result count

- **WHEN** a list endpoint reports `number_of_total_results` spanning several pages
- **THEN** the client walks offsets 100 at a time until the reported total is satisfied, and the assembled result count is cross-checked against `number_of_total_results`.

#### Scenario: Mid-walk page failure returns partial results with complete=False

- **WHEN** page 3 of 5 fails after pages 1–2 were retrieved with a non-auth error (rate limit, server error, malformed page)
- **THEN** the client returns the pages already retrieved with `complete=False` so the caller sees the incompleteness flag — it does not discard the partial results or report success.

#### Scenario: Auth failure propagates instead of degrading

- **WHEN** any page of the walk fails with a ComicVine authentication error (HTTP 401/403 or ComicVine error code 100)
- **THEN** the walk raises the typed auth error to the caller — it does not return an empty or partial result with `complete=False`, and the error message never contains the API key.

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

The system SHALL map each ComicVine issue to an issue record — issue ID, number, title, cover date, store date, image URLs — preserving non-integer issue numbers verbatim alongside a computed sort key, defaulting missing dates to NULL, and SHALL surface (not silently skip) issues lacking an issue number. When the response row carries `person_credits`, the mapped record SHALL additionally carry typed credit entries (CV person id, sanitized display name, verbatim + normalized role, per FRG-CRTR-001); an absent, empty, or malformed credits value SHALL map to an empty credit list without affecting the rest of the issue mapping.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §1.5 (GetIssuesInfo; unnumbered issues skipped; singleIssue person credits); sonarr-architecture.md §1.1 (decimal/string issue numbers).
- **Notes**: Divergence: Mylar silently drops unnumbered issues; foragerr records them unmonitored with a warning so have/total counts remain honest. Mylar's digital-date prose heuristic is dropped (unreliable; store date suffices). m5-creators-backbone: credits mapping added — sanitation and role normalization are FRG-CRTR-001's contract; this requirement only guarantees the mapping is total (credits present → typed entries, anything else → empty list, never an error).

#### Scenario: Non-integer issue numbers preserved verbatim as TEXT with a sort key

- **WHEN** a fixture volume contains issues `1`, `1.5`, `1.MU`, and `½`
- **THEN** each issue number is stored verbatim as TEXT (not coerced to a number) alongside a computed sort key that orders them correctly.

#### Scenario: Missing dates map to NULL, not a date sentinel

- **WHEN** an issue omits its store date
- **THEN** the mapped store date is NULL — never `'0000-00-00'` or any sentinel string.

#### Scenario: Unnumbered issue is surfaced, not dropped

- **WHEN** a fixture volume includes an issue lacking an issue number
- **THEN** the issue is recorded (unmonitored) with exactly one visible "unnumbered issue" warning rather than being silently skipped, keeping have/total counts honest.

#### Scenario: Credits map totally — entries or an empty list, never an error

- **WHEN** fixture issue rows carry (a) well-formed `person_credits`, (b) no credits field, and (c) a malformed credits value
- **THEN** (a) maps to typed credit entries, (b) and (c) map to an empty credit list with the issue otherwise mapped normally, and no row raises or is skipped

### Requirement: FRG-META-007 — Series search

The system SHALL provide a ComicVine series search by name (volumes endpoint with per-word name filters) that paginates to a bounded result count and annotates each candidate with plausibility signals — publication-year range, issue-count sanity for a target issue when given, already-in-library flag — and SHALL exclude publishers on a configurable ignore list. Ignore-list entries match case-insensitively, either exactly or — when an entry contains `*` — as a substring of the publisher name with the `*` removed (so `Panini*` covers Panini Verlag/España/France). Excluded volumes are counted and the count reported alongside the results (never a silent drop), and an explicit include-ignored query mode SHALL return them flagged as ignored rather than omitting them.

- **Milestone**: M1 (wildcard matching, hidden-count reporting, include-ignored mode added in M9: m9-publisher-ignore-defaults)
- **Source**: mylar-comicvine.md §1.6 (findComic heuristics), §5; mylar-feature-surface.md capability map META (ignored-publishers); Mylar `ignored_publisher_check` wildcard semantics (`.reference/mylar3/mylar/helpers.py`); M9 finding F17 (`docs/research/m9-user-sim-findings.md`).
- **Notes**: Keep Mylar's plausibility *annotations* but let the user (and the add flow) make the final choice — signals annotate and, since m4-add-new, order candidates (FRG-META-015); they never hard-drop except the publisher ignore list and never auto-pick. Result cap ~1000 with a visible truncation warning. The recoverable-count posture (vs Mylar's silent drop) is what makes a shipped default list (FRG-META-020) acceptable.

#### Scenario: Candidates annotated with plausibility signals, no auto-pick

- **WHEN** a known title is searched
- **THEN** each returned candidate carries plausibility annotations — similarity on the shared matching key, publication-year proximity, issue-count sanity for a target issue when supplied, and an already-in-library (`haveit`) flag for a series already present — and the search returns the annotated candidate list ordered per FRG-META-015 without auto-selecting one.

#### Scenario: Ignored-publisher volumes excluded but counted

- **WHEN** the results include volumes whose publisher matches the configurable ignore list (exactly, or via a `*` wildcard entry as a case-insensitive substring)
- **THEN** those volumes are absent from the returned candidates by default, the response reports how many were excluded, and other plausibility signals only annotate and order (do not hard-drop) the remaining candidates.

#### Scenario: Include-ignored mode returns flagged results

- **WHEN** the same search is issued with the explicit include-ignored option
- **THEN** the previously excluded volumes are returned in the candidate list, each flagged as ignore-listed, so a reader can recover a hidden edition without editing configuration.

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

The system SHALL download series and issue cover images referenced by ComicVine into a local cache, serve UI/OPDS artwork exclusively from that cache, refresh images older than a configurable age (default 30 days) lazily, and clean up orphaned cached images. Recording a newly cached or re-fetched cover SHALL be announced on the application event stream in the same transaction that records it, so connected clients repaint without a manual reload.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §1.7 (cover cache); mylar-feature-surface.md §8 (cache.py, 30-day freshness) and capability map META.
- **Notes**: UI browse and OPDS in the M1 slice need covers. Cover *regeneration* API and alternate-cover selection are B refinements folded here as Notes, not separate requirements. Amended by cv-budget-caching (owner-triaged bug, 2026-07-12): the cover-stamp write previously committed with no queued event, so open clients never learned the cover arrived — the frontend versions cover URLs by the stamp and repaints on push.

#### Scenario: Cover fetched through the limiter and egress policy, served from disk

- **WHEN** a series is added
- **THEN** its cover is downloaded through the process-global rate limiter, the egress policy, and the factory byte cap into `<config>/covers/<series_id>.jpg`, and the UI/OPDS render it from a local URL with no browser request to `comicvine.gamespot.com`.

#### Scenario: Re-fetch only when the CV image URL changes

- **WHEN** a refresh reports the same ComicVine image URL versus a changed one
- **THEN** the cached file is reused unchanged when the URL matches and re-fetched when the URL has changed.

#### Scenario: Missing cached image yields a deterministic 404

- **WHEN** artwork is requested for a series whose cached file is absent
- **THEN** the server returns a deterministic 404 from disk rather than reaching out to ComicVine at serve time.

#### Scenario: Newly cached cover is pushed to connected clients

- **WHEN** a refresh (re)fetches a series cover and commits the cover-cache stamp
- **THEN** a series-changed event is queued in that same write transaction and reaches connected WebSocket clients, and the unchanged-URL reuse path emits no event.

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

### Requirement: FRG-META-015 — Relevance ordering of lookup candidates

The system SHALL order ComicVine lookup candidates by the plausibility signals
it already computes, server-side, before returning them: primary key name
similarity on the shared matching key (descending), tiebreak publication-year
proximity when the searched term carries a year, with the upstream ComicVine
order preserved as a stable final tiebreak. The same ordering SHALL apply
identically to the full lookup and the bounded suggest endpoint (FRG-API-017).
Ordering is presentation only: no candidate is dropped, no candidate is
auto-selected, and the annotated signals remain on every candidate so the user
can see why a result ranks where it does. (This deliberately supersedes the
original M1 stance that signals never influence order; the never-drop /
never-auto-pick half of that stance is unchanged, per FRG-META-007.)

#### Scenario: Closest title match ranks first

- **WHEN** a search term closely matches one candidate's matching key and only
  loosely matches others
- **THEN** the closest match is returned first, ahead of alphabetically-earlier
  but less similar candidates

#### Scenario: Ordering drops nothing and picks nothing

- **WHEN** a lookup returns candidates including ones with very low similarity
- **THEN** every candidate the search produced is still present (count
  unchanged, ignored-publisher exclusion aside) and none is marked selected

#### Scenario: Lookup and suggest agree on order

- **WHEN** the same term is sent to the full lookup and the suggest endpoint
- **THEN** the candidates they share appear in the same relative order

### Requirement: FRG-META-016 — Per-path hourly request budget with defer-and-resume

The system SHALL account ComicVine requests per resource path (the first,
normalized URL path segment — the granularity ComicVine's own 200/hour limit
uses) over a rolling one-hour window, and SHALL refuse to issue a request on a
path whose soft budget (default 150/hour, configurable with a floor of 10 and
clamped to at most 200) is exhausted, raising a typed budget error that
carries the path bucket and the seconds until capacity returns instead of
sending the request. A budget refusal is a local decision: it SHALL NOT flip
the rate-limit degraded/back-off state, and it SHALL NOT block the caller
until capacity returns. Budget state SHALL be observable in the ComicVine
health payload (per-path usage for paths near or at their ceiling, plus an
exhausted flag), and every deferral SHALL be logged — never silent. Work
interrupted by a budget refusal SHALL resume without operator action:
bounded backfills (issue-credit fetches) stop cleanly for the run and later
runs pick up the unfinished remainder via their existing progress stamps;
command-based fetches record the failure and retry via their existing
staleness paths; interactive lookups surface the typed error through the
existing lookup-error surfacing with the resume time.

- **Milestone**: M6
- **Source**: ComicVine rate-limit documentation + owner's live per-path
  usage data (2026-07-12): 200/hour per resource path per key; `/issue` at
  75/hour under light use via the credits detail fetches. Gap analysis in
  the cv-budget-caching proposal.
- **Notes**: Complements, not replaces, the velocity gate (FRG-META-003) —
  spacing prevents bursts; the budget prevents hour-scale exhaustion the
  spacing math permits (~1800/hour at the 2 s default). Restart forgets the
  window (accepted: server-side 420/429 back-off remains the second line of
  defense). Single-process accounting by design — same posture as the
  process-global gate.

#### Scenario: Exhausted path refuses locally without touching other paths

- **WHEN** the configured hourly budget for one path bucket is consumed and a
  further request is attempted on that path while another path has remaining
  budget
- **THEN** the same-path request raises the typed budget error (carrying the
  bucket and seconds-until-resume) without any wire request and without
  flipping the degraded flag, and the other-path request proceeds normally.

#### Scenario: Credit backfill defers cleanly and resumes on a later run

- **WHEN** the issue-credit detail phase of a series refresh hits the budget
  refusal partway through its bounded target list
- **THEN** the refresh completes successfully with the credits fetched so
  far, the remaining issues stay unstamped, the deferral is logged, and a
  subsequent refresh run (with budget available) fetches the remainder.

#### Scenario: Budget state is visible in health

- **WHEN** a path bucket crosses its warning threshold and then exhausts
- **THEN** the ComicVine health payload reports that bucket's usage, ceiling,
  and seconds-until-resume, and an exhausted indicator, and the payload
  returns to its compact form once the window rolls over.

#### Scenario: Window rolls — capacity returns without operator action

- **WHEN** requests admitted more than one hour ago age out of the rolling
  window
- **THEN** new requests on the previously exhausted path are admitted again
  automatically.

#### Scenario: Ceiling configuration is clamped to ComicVine's documented limit

- **WHEN** the hourly budget setting is configured above 200 or below the
  floor
- **THEN** the effective ceiling is clamped into the documented bounds with a
  warning rather than accepting an unsafe value.

### Requirement: FRG-META-017 — Unchanged-volume refresh short-circuit

The system SHALL persist, per series, the `date_last_updated` value ComicVine
served on the volume detail of the last COMPLETE issue walk (stored verbatim,
compared by equality only, cleared when a walk is partial), and a series
refresh SHALL skip the issue pagination walk when the freshly fetched volume
detail carries the same value AND the last complete walk is more recent than
a configurable staleness bound (default 7 days). A short-circuited refresh
SHALL still perform issue-credit backfill for issues known (from the local
database) to lack credits, still maintain the cover cache, and still emit the
series-refreshed event; a full walk SHALL run whenever the stamp is absent,
the value differs, the bound is exceeded, or the operator forces it.

- **Milestone**: M6
- **Source**: ComicVine's own caching recommendation; Mylar's
  db_updater/watchlist pattern (mylar-comicvine.md §1.1) reduced to the
  per-series case. cv-budget-caching design decision 6.
- **Notes**: This is the response-caching measure with real traffic behind
  it: refresh-all across a stable library becomes ~1 request per series
  instead of a full walk each. FRG-META-010 (feed-based changed-since sync)
  remains a separate backlog item; the staleness bound plus stamp-clear-on-
  partial keep the periodic full walk as the correctness backstop.

#### Scenario: Unchanged stamp within the bound skips the walk

- **WHEN** a series refresh fetches the volume detail and its
  `date_last_updated` equals the stored stamp from a complete walk performed
  within the staleness bound
- **THEN** no issue-list request is made, the series' issues are left
  untouched, credit backfill targets database-known unstamped issues, and
  the series-refreshed event is still emitted.

#### Scenario: Changed stamp, missing stamp, or stale walk forces the full walk

- **WHEN** the fetched `date_last_updated` differs from the stored value, or
  no stamp is stored, or the last complete walk is older than the bound
- **THEN** the full issue pagination walk and reconciliation run exactly as
  before, and the stamp is stored afresh only if the walk was complete.

#### Scenario: Partial walk clears the stamp

- **WHEN** an issue walk ends incomplete (mid-pagination failure)
- **THEN** the stored stamp is cleared so the next refresh cannot
  short-circuit on top of a partial reconciliation.

### Requirement: FRG-META-018 — Runtime credential application across execution contexts

The system SHALL apply a ComicVine API key saved at runtime (Settings → General / `PUT /api/v1/config/general`) to all subsequent ComicVine requests in every execution context — request handlers, command workers, and scheduled tasks — without a process restart. The environment-variable precedence rule is unchanged: when `FORAGERR_COMICVINE_API_KEY` is set, the UI field is read-only and no runtime save occurs.

- **Milestone**: M9 (m9-cv-key-live-reload)
- **Source**: M9 simulated-user finding F1 (`docs/research/m9-user-sim-findings.md`) — the first-run killer: a UI-saved key worked for request-path lookups but never reached worker-context clients until restart, failing every fresh install's first series refresh with `ComicVineAuthError` while the docs promised "applies immediately, no restart needed".
- **Notes**: Root cause was a boot-time `Settings` snapshot in the command service's `HandlerContext`; the config-save path swaps `app.state.settings` but nothing refreshed the worker context. The fix keeps one write point (`_apply`) refreshing both. Worker *pool sizes* remain boot-time (documented restart-required) — only the settings object handlers read per-run is live.

#### Scenario: Key saved in the UI reaches the next worker-context refresh without restart

- **WHEN** no ComicVine key is configured, the operator saves a key via Settings → General, and a `refresh-series` command then runs in a command worker
- **THEN** the refresh's ComicVine requests carry the newly saved key and the refresh succeeds, with no process restart between the save and the run

#### Scenario: Subsequent config saves keep workers current

- **WHEN** an already-running deployment saves a *changed* ComicVine key via the same endpoint
- **THEN** the next command-worker ComicVine request uses the changed key, and the previous key is not sent again by any execution context

### Requirement: FRG-META-019 — ComicVine authentication-failure health truthfulness

WHEN a ComicVine request fails authentication (HTTP 401/403 — missing or invalid key), the system SHALL set the ComicVine health component to an error state whose message names the credential cause and whose remediation directs the operator to Settings → General, regardless of which execution context issued the request; the state SHALL clear automatically on the next successful ComicVine request. The auth-failure dimension is independent of the rate-limit back-off and per-path budget dimensions.

- **Milestone**: M9 (m9-cv-key-live-reload)
- **Source**: M9 simulated-user finding F1 — during the reproduced first-run failure, System → Health reported ComicVine **OK** while every worker request was rejected 401; the only diagnosis was a traceback in Logs.
- **Notes**: Mirrors the existing degraded-flag mechanics in `metadata/ratelimit.py` (module-level gate state read by `health/service.py::_comicvine_component`). Set at the single `_raise_for_status` choke point, cleared at the single success point, so no per-caller wiring.

#### Scenario: Worker-context auth failure surfaces on Health

- **WHEN** a command-worker ComicVine request is rejected with HTTP 401
- **THEN** the ComicVine component on System → Health reports an error state naming the authentication/key cause with remediation pointing at Settings → General

#### Scenario: Recovery clears the state without restart

- **WHEN** the auth-failure state is set and a later ComicVine request (any context) succeeds
- **THEN** the ComicVine component returns to OK with no operator action beyond fixing the key

### Requirement: FRG-META-020 — Curated default publisher ignore list

The system SHALL seed `comicvine_ignored_publishers` on fresh installs with a documented, curated default list of foreign-market reprint publishers (wildcard entries permitted), chosen so that publishers of original material are never on the default list. A persisted configuration keeps its stored value across upgrades — the new default applies only where no value was previously rendered — and the manual documents both the default list and how an upgraded install opts in.

- **Milestone**: M9 (m9-publisher-ignore-defaults)
- **Source**: M9 finding F17 — the #1 Add New result for "Ultimate Spider-Man" was a German Panini reprint (Marvel's 2024 ongoing ranked 9th); owner approval 2026-07-16. Upgrade semantics follow the `pull_enabled` precedent (v0.5.1).
- **Notes**: Conservative curation is a requirement, not a preference: Les Humanoïdes Associés publishes originals (The Incal, Barbarella) and stays OFF the default list; the recoverable hide (FRG-UI-032) is the safety valve for anything the default over-catches. The list constant lives in one place (config field default) so Settings, docs, and tests reference the same value.

#### Scenario: Fresh install seeds the default list

- **WHEN** foragerr first runs against an empty config directory and renders its documented `config.yaml`
- **THEN** `comicvine_ignored_publishers` is rendered with the curated default list, and a subsequent series search excludes (and counts) matching-publisher volumes out of the box.

#### Scenario: Upgraded install keeps its stored value

- **WHEN** foragerr starts against a `config.yaml` that already carries a `comicvine_ignored_publishers` value (including the empty string rendered by older releases)
- **THEN** the stored value is used unchanged — the new default does not overwrite it.

### Requirement: FRG-META-021 — Proxied metadata imagery

Candidate cover imagery from the metadata provider SHALL be served to the
browser same-origin through an authenticated proxy endpoint, never
hotlinked — so the SPA's self-contained Content-Security-Policy
(FRG-SEC-006) holds while lookup and review surfaces show covers. The
proxy SHALL enforce, server-side, in order: the request is authenticated
(default-deny perimeter); the target URL is HTTPS with a host on the
ComicVine media allowlist (exact host or dot-boundary subdomain); the
fetch runs over the hardened external egress profile (FRG-SEC-001,
per-hop validation); the response is verified as an image by magic bytes
before any byte is served; a streaming size cap bounds the transfer. A
bounded in-memory cache MAY serve repeats; cache entries are keyed by
exact URL.

#### Scenario: Allowlisted cover proxies same-origin

- **WHEN** an authenticated client requests the proxy with an HTTPS ComicVine media URL
- **THEN** the image bytes are returned same-origin with the sniffed image content type, and the SPA renders it under the unchanged self-contained CSP

#### Scenario: Off-allowlist and non-HTTPS targets are refused

- **WHEN** the proxy is asked for a URL on any non-allowlisted host (including a bare-suffix lookalike of an allowlisted host) or a non-HTTPS URL
- **THEN** the request is refused with a 400 naming the constraint, and no outbound fetch is attempted

#### Scenario: Non-image content never reaches the client

- **WHEN** the allowlisted host answers with content whose magic bytes are not a known image format (HTML, JSON, text)
- **THEN** the proxy refuses with a 502-class error and serves zero body bytes to the client

#### Scenario: Unauthenticated requests are denied

- **WHEN** the proxy is requested with no session or API key
- **THEN** the perimeter rejects it with 401 before any fetch logic runs

