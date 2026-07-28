# sources — delta for m11-cv-budget

## ADDED Requirements

### Requirement: FRG-SRC-013 — Frugal, convergent proposal enrichment

The system SHALL order source-enrichment work by least-recent attempt
rather than row identity: every enrichment pass stamps the rows it
touches with an attempt time, the pending set is walked
never-attempted-first then oldest-attempt-first, and a row whose
computation failed or was deferred can therefore delay only its own
retry — never the first attempt of rows behind it. Rows whose
ComicVine consultation errored SHALL respect a configurable minimum
re-attempt spacing (default one day) on the scheduled path; operator
paths (restore, the per-row search) are never spaced. The system SHALL
provide an operator-triggered, resumable bulk recompute that refreshes
stored proposals predating the ComicVine-first universe (and, on
explicit request, no-plausible-match markers) in batches through the
batch lane (FRG-META-022), stopping cleanly on budget refusal and
resuming from its attempt-ordering on the next run; it touches only
rows still in review — matched and ignored rows are never recomputed.
No-plausible-match markers computed without a ComicVine key SHALL
become eligible for recomputation when a key is configured. Budget
exhaustion continues to leave affected rows un-proposed and retryable
(the FRG-SRC-010 invariant); attempt stamps change order, never
eligibility.

#### Scenario: A failing head cannot starve the tail

- **WHEN** nightly enrichment repeatedly defers or errors on the same
  early rows while later rows have never been attempted
- **THEN** the next run attempts the never-attempted rows first, and
  the previously failing rows retry only at their turn (and, for
  errored rows, only after the re-attempt spacing)

#### Scenario: Bulk recompute is resumable and budget-polite

- **WHEN** the operator triggers a recompute of pre-ComicVine-universe
  proposals on a large source and the batch lane's budget runs out
  mid-walk
- **THEN** the run stops cleanly having refreshed a prefix, no row
  loses its existing proposal to the interruption, and re-running the
  action continues from the least-recently-attempted rows until the
  backlog is done

#### Scenario: Operator decisions are never recomputed

- **WHEN** a bulk recompute walks rows that include matched and
  ignored entitlements
- **THEN** only rows still in review are recomputed; matched and
  ignored rows are untouched

#### Scenario: A new key unlocks catalog verdicts

- **WHEN** a deployment that stored library-fallback no-match markers
  configures a ComicVine key
- **THEN** those markers become eligible for recomputation so the rows
  can receive a catalog verdict instead of remaining frozen on a
  keyless one
