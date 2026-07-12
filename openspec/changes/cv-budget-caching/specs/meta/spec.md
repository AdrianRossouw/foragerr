# Delta: meta — cv-budget-caching

## ADDED Requirements

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

## MODIFIED Requirements

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

#### Scenario: Orphaned cached images cleaned up

- **WHEN** a series is deleted and the cleanup pass runs
- **THEN** its cached artwork is removed.

#### Scenario: Newly cached cover is pushed to connected clients

- **WHEN** a refresh (re)fetches a series cover and commits the cover-cache stamp
- **THEN** a series-changed event is queued in that same write transaction and reaches connected WebSocket clients, and the unchanged-URL reuse path emits no event.
