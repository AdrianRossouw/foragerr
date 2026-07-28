# ui — delta for m11-acquisition-responsiveness

## ADDED Requirements

### Requirement: FRG-UI-041 — Per-indexer search outcomes

The web UI SHALL render the interactive search's per-indexer outcomes
(FRG-API-008) beside the results: a compact strip naming each indexer's
result — searched, timed out (with the bounding budget), failed, or
backing off — so a partial result is visibly partial and a slow indexer
is named rather than inferred. A fully successful search renders
quietly (no alarm chrome for the normal case).

#### Scenario: A timed-out indexer is named at the results

- **WHEN** an interactive search returns with one indexer timed out
- **THEN** the results panel shows the outcome strip naming that
  indexer as timed out with the budget, the returned rows render as
  usual, and grabbing them works unchanged

#### Scenario: The normal case stays quiet

- **WHEN** every indexer completes
- **THEN** the outcome strip renders its quiet all-searched form with
  no warning styling
