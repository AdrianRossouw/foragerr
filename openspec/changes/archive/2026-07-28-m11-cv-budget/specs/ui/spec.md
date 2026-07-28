# ui — delta for m11-cv-budget

## ADDED Requirements

### Requirement: FRG-UI-040 — ComicVine budget meter

The web UI SHALL render the ComicVine budget meter from the structured
health detail (FRG-API-025): a full per-path meter in Settings →
General beside the ComicVine credential (usage, ceiling, batch share,
resume time, lane-paused state), and a compact indicator on the Sources
review surface that appears only when a bucket is above the warning
fraction — quiet when there is nothing to say. Interactive lookup
surfaces SHALL show the backend's typed budget message (with its resume
time) when a search is refused for budget, never a generic failure
string.

#### Scenario: Settings shows the full meter

- **WHEN** the operator opens Settings → General with budget usage
  present
- **THEN** each active path bucket renders usage against ceiling with
  the batch share and any resume countdown, updating with health

#### Scenario: The review surface warns only when it matters

- **WHEN** the operator works the review queue while all buckets are
  below the warning fraction
- **THEN** no budget chrome is shown; when a bucket crosses the
  fraction, a compact indicator appears with the bucket and usage

#### Scenario: A budget-refused search says when to retry

- **WHEN** a lookup, suggest, or row search is refused by the budget
- **THEN** the outcome note carries the typed message's resume time
  (the same fidelity the add path already has), not a generic
  try-again string
