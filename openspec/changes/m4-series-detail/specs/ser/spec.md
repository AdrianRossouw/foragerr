# ser delta — m4-series-detail

## ADDED Requirements

### Requirement: FRG-SER-020 — Trade containment model (declared, display-only)

The system SHALL let the operator declare which issues a collected edition
collects: a containment record maps one issue of a trade-typed series (one
collected book) to a target series plus a contiguous issue range expressed
as ordering-key bounds, with one record per contiguous sub-range (so
non-contiguous collections and multi-series omnibuses are multiple
records). Records carry a human-readable range label and a
`source`/`confidence` provenance (v1 writes only `declared`). Containment
SHALL live entirely in a dedicated side table — no column on `series` or
`issues` — and SHALL be display-only: the wanted derivation and series
statistics SHALL NOT reference the containment table, extending the
FRG-SER-019 never-suppress invariant, and this absence SHALL be asserted by
the same compiled-SQL test technique that proves FRG-SER-019. Deleting the
trade issue or the target series SHALL remove the dependent containment
records and nothing else.

- **Milestone**: M4 (m4-series-detail)
- **Source**: owner design handoff §2 (Collected in / Collections);
  m3-trade-typing deferred non-goal; 2026-07-10 containment research
  (Mylar cv.py TPB scraping; sanitizer strips CV data-ref-id links →
  declared-only v1).
- **Notes**: Ordering-key bounds (not issue-id endpoints) keep ranges
  stable under ComicVine renumbering and directly comparable. Derived
  suggestions from description text are backlog; the provenance columns
  exist so that lands without a migration.

#### Scenario: Declared range round-trips

- **WHEN** the operator declares that a trade issue collects issues #1–#6 of a target series (and separately #8)
- **THEN** two containment records exist with that trade issue, the target series, ordering-key bounds matching the chosen endpoint issues, and labels "#1–#6" and "#8", and reading them back yields the same ranges

#### Scenario: Containment never touches wanted

- **WHEN** the wanted derivation and series statistics queries are compiled
- **THEN** neither references the containment table or its columns (asserted mechanically), and declaring or deleting containment for a fully-collected range changes no issue's wanted state

#### Scenario: Cascade cleanup

- **WHEN** the trade issue (or the target series) of a containment record is deleted
- **THEN** the containment record is removed, and no file, issue, monitored flag, or wanted row elsewhere is affected
