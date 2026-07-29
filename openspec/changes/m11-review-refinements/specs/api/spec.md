# api — delta for m11-review-refinements

## MODIFIED Requirements

### Requirement: FRG-API-008 — Release endpoint: interactive search with cached grab

The API SHALL provide `GET /release?issueId=` performing a live interactive search that returns every decision — approved, temporarily rejected, and rejected — each with human-readable rejection reasons, quality/format, score, indexer, size, and age; results SHALL be cached server-side (~30 min, keyed indexerId+guid) so that `POST /release {guid, indexerId}` grabs from cache and returns a clear "search again" error when the cache entry has expired. The cache SHALL record each decision's **approved verdict** alongside its grab hand-off. `POST /release` SHALL grab an approved cached release; a cached release whose decision was **not** approved SHALL be refused with a typed 409-class error naming the constraint **unless** the request carries `force: true`, in which case the grab proceeds and is recorded as an operator-forced grab (`triggered_by="interactive-forced"`) — so the quality rules are enforced by default and bypassed only by a deliberate, audited operator action. The response SHALL additionally carry per-indexer outcomes (searched, timed out with the bounding budget, failed, backing off — FRG-SRCH-015) as an additive field, so a partial result is machine-readably partial.

- **Milestone**: M1 (grab approval gate + force override in M11, m11-review-refinements)
- **Source**: sonarr-architecture.md §7.2 release endpoint semantics ("Copy this exactly"), §2.4 interactive search returning rejected decisions; rig dogfood 2026-07-28 (the all-rejected "Absolute Green Lantern" case).
- **Notes**: This is the vertical slice's "search → grab" contract. Rejection reasons come from the decision engine (SRCH/decision area) — this owns transport only. The approved verdict rides the cached entry (migration 0030, additive) so grab can enforce it without a re-search; before this change the grab path enforced nothing, so a rejected release was silently grabbable by anyone holding its guid.

#### Scenario: Live search returns every decision including rejections, sorted by the comparator

- **WHEN** a client calls `GET /api/v1/release?issueId=<id>`
- **THEN** a live multi-indexer search runs and the response includes every decision — approved, temporarily rejected, and rejected — each carrying user-visible rejection reasons, quality/format, score, indexer, size, and age, and the rows are ordered by the decision comparator

#### Scenario: Response rows carry the indexerId+guid cache key and are cached ~30 min

- **WHEN** a search response is returned
- **THEN** each row carries its `indexerId` + `guid` cache key, the results are held in a server-side cache for approximately 30 minutes with housekeeping that prunes expired entries, and each cached entry records whether its decision was approved

#### Scenario: POST on an approved cache hit enqueues the grab command and returns it

- **WHEN** a client calls `POST /api/v1/release {indexerId, guid}` for an approved release while a matching cache entry is live
- **THEN** the endpoint enqueues the grab command (`triggered_by="interactive"`) and returns that command resource, without re-running a search

#### Scenario: A rejected release is refused unless forced

- **WHEN** a client calls `POST /api/v1/release {indexerId, guid}` for a cached release whose decision was NOT approved, first without `force` and then with `force: true`
- **THEN** the unforced call is refused with a typed 409-class error naming the quality-rule constraint and enqueues no grab, while the forced call enqueues the grab recorded as `triggered_by="interactive-forced"` — the same grab hand-off, deliberately overriding the rules

#### Scenario: POST on a cache miss or expiry returns a uniform 404-class error, never a silent re-search

- **WHEN** a client calls `POST /api/v1/release {indexerId, guid}` for a key that is absent or whose cache entry has expired
- **THEN** the endpoint returns a deterministic 404-class response in the uniform error shape and does not silently re-run the search, whether or not `force` was supplied

#### Scenario: Per-indexer outcomes are on the wire

- **WHEN** a search completes with mixed indexer outcomes
- **THEN** the response envelope carries the decision rows and a
  per-indexer outcomes list naming each indexer's result (searched /
  timed out with its budget / failed / backing off, with candidate
  counts), and a fully successful search reports every indexer as
  searched. (Pre-1.0 shape change: the former bare decision array
  became this envelope; the bundled frontend is the sole consumer and
  moved in lockstep — recorded in the release's upgrade notes.)
