# Spec Delta: ser (wanted-count-consistency)

## MODIFIED Requirements

### Requirement: FRG-SER-009 — Series statistics

The system SHALL compute per-series statistics — issue count, issue-file count (have/total), size on disk, missing count, and next/last release date — via aggregation over issue and issue-file records, exposed on series list and detail resources. The **missing count** SHALL be the count of that series' issues satisfying the same "wanted" predicate as `wanted_issues()` (FRG-SER-004): series monitored AND issue monitored AND issue released (store/cover date passed or unknown-but-listed) AND no issue file present. There SHALL be a single definition of "missing" — the missing count and the Wanted list (FRG-API-012) SHALL be derived from the same predicate and can never disagree — so unreleased (future-dated) and unmonitored file-less issues are NOT counted as missing. The `have`/`total` figures remain the raw issue-file and issue counts.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.3 (SeriesResource statistics); mylar-feature-surface.md capability map SER (Have/Total).
- **Notes**: Derived, never stored counters that can drift (fixes Mylar's recount-on-rescan model). Missing count aligned to FRG-SER-004 (wanted-count-consistency): the earlier `issue_count - file_count` shortcut over-counted unreleased/unmonitored issues.

#### Scenario: Statistics aggregate have/total and size on disk

- **WHEN** a series with 10 issues and 4 issue-file rows is fetched via list or detail
- **THEN** the response reports 4/10 (have/total), a non-zero size on disk equal to the sum of its file sizes, and derived next/last release dates

#### Scenario: Statistics update without a manual recount

- **WHEN** a fifth issue-file row is added for that series and it is fetched again
- **THEN** the reported have count is 5/10 and the size on disk grows accordingly, with no recount action invoked

#### Scenario: Statistics are computed per request, not stored

- **WHEN** the schema is inspected and a statistics-bearing response is served
- **THEN** no stored counter columns (issue count, file count, missing count, size) exist; each figure is produced by aggregation at request time

#### Scenario: Missing count is the wanted count — one definition

- **WHEN** a monitored series has: 3 released monitored file-less issues, 2 unreleased (future-dated) monitored file-less issues, 1 unmonitored released file-less issue, and 4 issues with files
- **THEN** the series' `missing_count` is 3 (the released, monitored, file-less issues only) — not `issue_count - file_count` (which would be 6) — and it equals the number of rows `wanted_issues()` returns for that series; the unreleased and unmonitored file-less issues are excluded from missing exactly as they are excluded from the Wanted list
