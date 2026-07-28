# api — delta for m11-cv-budget

## ADDED Requirements

### Requirement: FRG-API-025 — Structured budget state on the health surface

The system SHALL expose the ComicVine budget's structured state on the
existing authenticated system-health surface as an additive component
detail: per path bucket, the used count, the effective ceiling, the
batch-lane usage against its share, and the seconds until capacity
returns, plus the degraded and exhausted indicators — the numbers the
gate already computes, no new endpoint and no new unauthenticated
disclosure. Buckets below the warning fraction MAY be omitted for
compactness; the shape SHALL be stable for UI consumption
(FRG-UI-040).

#### Scenario: The meter's numbers are served, authenticated, additive

- **WHEN** an authenticated client reads system health while a path
  bucket is above the warning fraction
- **THEN** the ComicVine component carries the structured budget detail
  (bucket, used, ceiling, batch share usage, resume seconds) alongside
  its existing state and message fields, and clients unaware of the new
  field are unaffected

#### Scenario: No unauthenticated leakage

- **WHEN** the unauthenticated health endpoint is read
- **THEN** it carries no budget numbers — the slim unauthenticated
  surface is unchanged
