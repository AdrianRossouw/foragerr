# api delta — m4-series-detail

## ADDED Requirements

### Requirement: FRG-API-022 — Containment resources

The API SHALL surface trade containment (FRG-SER-020) read and write:
(1) the per-series issues listing SHALL carry each issue's collected-in
memberships (the trade series id/title, its book-type, and the collected
book's issue id) so the detail table can render chips without N+1 calls;
(2) a per-series collections resource SHALL list containment from BOTH
directions — collected books declaring ranges that target the series, and,
for a trade-typed series, its own issues' declared contents — each with the
trade series/issue identifiers, book-type, range labels with their resolved
endpoint issue ids (so an edit dialog can pre-fill), release date (store
date preferred, cover date fallback), and a request-time singles-coverage
status (`collected` when every issue in every range has a file, `partial`
when some do, `none` when none do) computed read-only;
(3) declare/replace/delete endpoints SHALL manage a trade issue's
containment records, validating that the target series exists and is not
the trade's own series, that both endpoint issues belong to it, that the
bounds are ordered, and that the ranges list is bounded — rejecting
otherwise with the API's standard error shape. Writes SHALL touch only
containment records (no series/issue/file mutation).

- **Milestone**: M4 (m4-series-detail)
- **Source**: owner design handoff §2; FRG-SER-020.
- **Notes**: Coverage status is computed per request over
  file-presence within the ordering-key range (the display-only rollup
  pattern); it is never persisted.

#### Scenario: Issues listing carries collected-in chips data

- **WHEN** a series' issues are listed and some fall inside declared ranges
- **THEN** exactly those issues carry the collecting trade's identity and book-type, and issues outside every range carry none

#### Scenario: Collections rollup with coverage

- **WHEN** the collections resource is read for a series where one declared range is fully file-backed, another partially
- **THEN** the response lists both collected books with their range labels and statuses `collected` and `partial` respectively, and a range with no files reads `none`

#### Scenario: Declaration is validated

- **WHEN** a declaration names a target series the endpoint issues do not belong to, or bounds out of order
- **THEN** the write is rejected with the standard error shape naming the field, and no containment record is created

#### Scenario: Writes are containment-only

- **WHEN** containment records are declared, replaced, or deleted for a trade issue
- **THEN** only containment rows change — no issue, series, file, monitored flag, or wanted result is affected
