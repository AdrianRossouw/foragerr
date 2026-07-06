# meta — delta for m2-lookup-error-surfacing

## MODIFIED Requirements

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
