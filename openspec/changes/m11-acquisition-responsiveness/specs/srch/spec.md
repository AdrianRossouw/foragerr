# srch — delta for m11-acquisition-responsiveness

## ADDED Requirements

### Requirement: FRG-SRCH-015 — Per-indexer interactive time budget with partial results

The system SHALL bound each indexer's share of an interactive search
with a configurable per-indexer time budget (default 20 seconds,
clamped 5–60): when the budget lapses, decisions from indexers that
completed are returned immediately, still-running indexers are
cancelled cleanly between politeness-gated requests, and each such
indexer is reported as an explicit timed-out outcome carrying the
budget that bounded it. The budget SHALL apply to the interactive path
only — scheduled backlog searches keep their politeness-first,
unbudgeted behavior. The ENFORCED budget SHALL additionally be bounded
by the deployment's configured listener request guard (FRG-NFR-014)
less a margin, so no configured value inside the documented range can
let an interactive search outlive that guard — deployment-level
listener-timeout workarounds are not required for slow indexers.

#### Scenario: The slowest indexer no longer holds the search

- **WHEN** an interactive search fans out to three indexers and one is
  still paging when the per-indexer budget lapses
- **THEN** the response returns within the budget envelope carrying
  both finished indexers' complete decisions, and the slow indexer is
  reported as timed out — never a whole-request 503

#### Scenario: A timed-out indexer is an outcome, not an error

- **WHEN** an indexer exceeds its budget
- **THEN** its outcome names the indexer and the budget, no partial
  page from it is silently mixed in, its failure/backoff bookkeeping is
  not corrupted by the cancellation, and the searched indexers' rows
  grab exactly as before

#### Scenario: The budget can never outlive the listener guard

- **WHEN** a budget inside the documented range is configured above the
  deployment's listener request guard
- **THEN** the enforced budget is clamped below that guard with a
  warning, so the setting cannot reinstate the request-guard failure
  the budget exists to prevent

#### Scenario: Backlog stays politeness-first

- **WHEN** the scheduled backlog search runs against a slow indexer
- **THEN** no time budget cancels it — scheduled work waits politely

## MODIFIED Requirements

### Requirement: FRG-SRCH-014 — Interactive search

The system SHALL provide an interactive search endpoint that runs a live search over interactive-enabled indexers and returns every decision — approved, temporarily rejected, and rejected — with its rejection reasons, caching results (~30 min, keyed indexer+guid) so a subsequent grab request references the cache and returns a clear "search again" error when expired. The live search SHALL apply the FRG-SRCH-015 per-indexer time budget, return partial results when an indexer exceeds it, and include per-indexer outcomes (searched, timed out, failed, backing off) alongside the decisions.

- **Milestone**: M1
- **Source**: sonarr-arch §2.4 (interactive path), §7.2 (release endpoint semantics)
- **Notes**: Pulled into M1 despite not being named in the slice: it is the primary debugging/UX surface for the q=-only search problem and costs little once the decision engine records reasons (which M1 already requires).

#### Scenario: Returns every decision with full reason lists, comparator-sorted

- **WHEN** an interactive search runs over interactive-enabled indexers
- **THEN** the response includes every decision — Approved, TemporarilyRejected, and Rejected — each carrying its full rejection reason list, sorted by the comparator chain (approved best-first).

#### Scenario: Each row carries an indexerId+guid cache key

- **WHEN** the interactive search returns a row
- **THEN** the row carries its indexerId + guid cache key and the decision set is cached server-side for approximately 30 minutes.

#### Scenario: Grab from cache references the cached decision

- **WHEN** a grab request references a row's indexerId+guid while its cache entry is still valid
- **THEN** the grab uses the cached decision without re-running the search.

#### Scenario: Grab after cache expiry returns a deterministic 404-class error

- **WHEN** a grab request references an indexerId+guid whose cache entry has expired
- **THEN** the endpoint returns a deterministic 404-class "search again" error and never silently re-runs the search.

#### Scenario: Partial results carry their outcomes

- **WHEN** an interactive search returns with one indexer timed out
- **THEN** the cached decision set is the partial set, the response's
  per-indexer outcomes mark the timeout, and grabbing a returned row
  works identically to a complete search
