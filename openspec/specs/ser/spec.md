# SER — Series & Library Management Specification

## Purpose

Baseline requirements for series & library management, mined from the
Phase 1 reference research (`docs/research/`). Baseline depth per the Phase 2 scope
decision: SHALL + coarse acceptance; scenario-level elaboration happens in the
milestone change that implements each requirement (FRG-PROC-003, FRG-PROC-009).
## Requirements
### Requirement: FRG-SER-001 — Series entity from ComicVine volume

The system SHALL persist each watched series as a record keyed by its ComicVine volume ID, storing at minimum title, clean/sort title, publisher, start year, status (continuing/ended), overview, cover image reference, path, root folder, format-profile reference, monitored flag, added timestamp, and last-metadata-sync timestamp, with the ComicVine volume ID unique across the library.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §1.1 (Series entity); mylar-feature-surface.md capability map SER (watchlist).
- **Notes**: Mylar's Active/Paused/Loading series status collapses into `monitored` (bool) plus transient command state — deliberate divergence (D1). ComicVine ID conventions (4050- volume prefix) are normalized at the META boundary, not stored in SER keys. The format-profile reference points at a profile defined by FRG-QUAL-001 (default assigned per FRG-QUAL-002).

#### Scenario: Duplicate ComicVine volume is rejected

- **WHEN** a client POSTs `/api/v1/series` for a `cv_volume_id` that already has a series row
- **THEN** the request fails with a client error, no second row is inserted, and the `series.cv_volume_id` unique constraint holds (exactly one row for that volume remains)

#### Scenario: Stored series round-trips all baseline fields

- **WHEN** a series is added and then fetched via `GET /api/v1/series/{id}`
- **THEN** the response exposes title, sort/clean title, publisher, start year, status, overview, cover reference, path, root folder, format-profile reference, monitored flag, added timestamp, and last-metadata-sync timestamp, each matching the persisted row

#### Scenario: New series receives the default format profile

- **WHEN** a series is added without an explicit `format_profile_id`
- **THEN** the persisted row's `format_profile_id` references the seeded default profile (FRG-QUAL-002), and the detail response reflects that assignment

### Requirement: FRG-SER-002 — Issue entity

The system SHALL persist one issue record per ComicVine issue of a watched series, storing ComicVine issue ID, series reference, issue number as a decimal-and-string-safe value (supporting `1`, `1.5`, `1.MU`, `½`), title, cover date, store date, issue type (regular/annual/special/TPB-content), monitored flag, and issue-file reference (null when no file).

- **Milestone**: M1
- **Source**: sonarr-architecture.md §1.1 (Episode entity, comic mapping note on decimal/string issue numbers); mylar-comicvine.md §1.5 (GetIssuesInfo fields).
- **Notes**: No season layer (Sonarr's embedded-season trick shows the middle tier is droppable). Dates are nullable typed fields, never `'0000-00-00'` sentinels (mylar-comicvine.md §3.7).

#### Scenario: Non-integer issue numbers persist verbatim as text

- **WHEN** a series whose ComicVine issues include `1`, `1.5`, and `1.MU` is refreshed
- **THEN** three issue rows exist, each keyed by its `cv_issue_id`, with `issue_number` stored as TEXT holding exactly `1`, `1.5`, and `1.MU` (no numeric coercion or truncation)

#### Scenario: Issues sort in reading order via the persisted ordering key

- **WHEN** those issues are listed via `GET /api/v1/issues?seriesId={id}` sorted by reading order
- **THEN** they are returned ordered `1`, `1.MU`, `1.5` using the persisted ordering key, independent of insertion order
- **Note (corrected 2026-07-05, m1-library-metadata)**: an earlier draft of this scenario listed the order as `1`, `1.5`, `1.MU`. The persisted ordering key deliberately reuses the single shared ordering implementation from FRG-IMP-020 (`foragerr.parser.ordering.sort_key`) rather than a second, divergent rule — under that implementation `1.MU` shares `1`'s base numeric value (and sorts before any strictly greater value like `1.5`) by its own established, tested tie-break rules. The example was wrong, not the implementation; corrected here to match the actual, intentional, single-ordering-implementation behavior.

#### Scenario: Absent dates and files are stored as null, not sentinels

- **WHEN** an issue arrives from ComicVine with no store date and no file on disk
- **THEN** its `store_date` and issue-file reference are persisted as null typed values (never `'0000-00-00'` or a placeholder file reference), and the API surfaces them as null

#### Scenario: Issues are independently monitorable

- **WHEN** a single issue's monitored flag is toggled via `PUT /api/v1/issues/{id}`
- **THEN** only that issue's `monitored` value changes and its siblings' flags are unaffected

### Requirement: FRG-SER-003 — Two-level monitored flags

The system SHALL provide independent monitored flags at series level and issue level, and SHALL treat an issue as eligible for automatic acquisition only when both its own flag and its series' flag are set.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §1.3 (monitored flags, MonitoredEpisodeSpecification); §8 "two-level monitored flags".
- **Notes**: The single most load-bearing Sonarr behavior per the research doc. Replaces Mylar's per-issue Wanted status writes (D1).

#### Scenario: Unmonitored series suppresses eligibility of its monitored issues

- **WHEN** a series is unmonitored while some of its issues remain monitored
- **THEN** the wanted/eligible-for-acquisition query returns none of that series' issues, even though the issue-level flags are still set

#### Scenario: Re-monitoring the series restores eligibility without touching issue flags

- **WHEN** the series is re-monitored
- **THEN** its previously-monitored, released, file-less issues reappear in the wanted/eligible query, and no issue-level `monitored` value was written during either toggle

#### Scenario: Eligibility requires both flags set

- **WHEN** the series is monitored but a given issue is unmonitored
- **THEN** that issue is not eligible for automatic acquisition, confirming the AND of the two flags

### Requirement: FRG-SER-004 — Derived wanted state

The system SHALL compute "wanted" as a derived predicate — series monitored AND issue monitored AND issue released (store/cover date passed or unknown-but-listed) AND no issue file present — and SHALL NOT persist wanted as a stored issue status.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §1.1 ("Wanted/missing is derived"), §8; contrast mylar-feature-surface.md §3 (stored status lifecycle).
- **Notes**: D1. Download-in-flight suppression of re-grabs is the queue/decision engine's job (QueueSpecification analogue), not an issue status.

#### Scenario: No wanted column exists in the schema

- **WHEN** the database schema is inspected by the schema-inventory test
- **THEN** no table exposes a `wanted` (or equivalent stored wanted-status) column; wanted is only ever computed by the `wanted_issues()` query

#### Scenario: Importing a file removes an issue from wanted with no status write

- **WHEN** an issue-file row is created for a wanted issue
- **THEN** the wanted query no longer returns that issue, and no issue-status column was updated to effect the change

#### Scenario: Deleting the file returns the issue to wanted

- **WHEN** that issue's file row is removed while the series and issue remain monitored and the issue is released
- **THEN** the wanted query returns the issue again, purely by re-evaluation of the predicate

#### Scenario: Unreleased monitored issues are not wanted

- **WHEN** a monitored, file-less issue has a future store/cover date
- **THEN** the wanted query excludes it until the release date has passed

### Requirement: FRG-SER-005 — Add flow (add → refresh → scan → optional search)

When a series is added, the system SHALL execute a chained sequence: fetch and persist metadata and issues from ComicVine, apply user add-options (root folder, format profile, monitoring strategy, search-on-add), build and validate the series path, scan the path for existing files, and, if requested, queue a search for missing monitored issues — with add-options cleared once the chain completes.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §1.2 (add lifecycle, AddOptions), §8.
- **Notes**: Chain runs as events/commands on the backbone (SCHED area owns the command queue). Path validation includes root-folder existence and slug/path uniqueness (AddSeriesValidator analogue).

#### Scenario: Add validates before persisting

- **WHEN** `POST /api/v1/series` is called with a non-existent CV volume, an unregistered root folder, or a duplicate `cv_volume_id`
- **THEN** the request is rejected with a client error and no series row, command, or path is created

#### Scenario: A successful add enqueues the chain as separate commands visible in job history

- **WHEN** a valid series is added
- **THEN** the series row is persisted carrying its `add_options`, and a `RefreshSeriesCommand` for the series is enqueued on the persisted command backbone, each subsequent step (`ScanSeriesCommand`, and `SeriesSearchCommand` when requested) appearing as its own entry observable via the command/job-history API

#### Scenario: The chain populates issues, matches files, and clears add-options

- **WHEN** the add chain runs to completion for a series added with existing files under its path
- **THEN** issue records are present, existing on-disk files are matched to issue-file rows by the parser, `add_options` is cleared on the series row, and the sequence is restart-safe (an interrupted chain resumes from the persisted queue rather than restarting the add)

#### Scenario: Search-on-add enqueues a recognized command

- **WHEN** a series is added with search-on-add enabled
- **THEN** a `SeriesSearchCommand` is enqueued and recorded in job history with real dedup/history semantics (inert stub until change 4), observable via the command API

### Requirement: FRG-SER-006 — Add-time monitoring strategies

The system SHALL support add-time monitoring strategies of at least: all issues, future issues only, missing issues only, existing issues only, first issue only, and none, applied once during the add flow to set per-issue monitored flags.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §1.3 (MonitorTypes, EpisodeMonitoredService).
- **Notes**: M1 may ship with "all" + "none" wired in UI and the rest API-only; the strategy enum and application service belong to the slice because add-options pass through it. "Pilot"→"first issue" is the comic translation.

#### Scenario: Each strategy yields its documented per-issue monitored pattern

- **WHEN** the same test series is added under each strategy (all, future, missing, existing, first, none)
- **THEN** the resulting per-issue `monitored` flags match the strategy definition (e.g. "all" monitors every issue, "none" monitors none, "first" monitors only the first-in-reading-order issue), applied over the issues persisted by the refresh step

#### Scenario: The strategy is applied exactly once then cleared

- **WHEN** the add chain applies the monitoring strategy and completes
- **THEN** the strategy has set issue flags a single time, `add_options` is cleared, and a subsequent metadata refresh does not re-apply the add-time strategy (later issues are governed by the monitor-new-items policy, FRG-SER-007)

### Requirement: FRG-SER-007 — Monitor-new-items policy

Each series SHALL carry a monitor-new-items policy (all | none) that determines whether issues newly discovered during metadata refresh are created with their monitored flag set.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §1.1 (MonitorNewItems), §1.2 step 3.
- **Notes**: This is the Sonarr translation of Mylar's `AUTOWANT_UPCOMING` — auto-wanting happens through monitoring policy at refresh time, not through pull-list status writes (D1, D4). PULL requirements depend on this.

#### Scenario: Policy "all" monitors newly discovered issues

- **WHEN** a refresh discovers a CV issue not previously in the library and the series' monitor-new-items policy is "all"
- **THEN** the inserted issue row is created with `monitored` true (hence wanted once released)

#### Scenario: Policy "none" leaves newly discovered issues unmonitored

- **WHEN** a refresh discovers a new CV issue and the policy is "none"
- **THEN** the inserted issue row is created with `monitored` false and is excluded from the wanted query

#### Scenario: Policy governs refresh inserts, not the add-time strategy

- **WHEN** a series added under the "existing/missing" add strategy later gains a brand-new issue via refresh
- **THEN** that issue's monitored flag is set from the monitor-new-items policy, independent of the strategy applied at add time

### Requirement: FRG-SER-008 — Root folders and series paths

The system SHALL support one or more configured root folders; each series SHALL have a path defaulting to `<root folder>/<templated series folder>` created on add, with the folder-name template configurable and the path overridable per series.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §1.2 step 1, §5.5 (RootFolderService); mylar-feature-surface.md capability map SER (multiple destination dirs, create-folders-on-add, per-series location).
- **Notes**: Subsumes Mylar's `MULTIPLE_DEST_DIRS` and per-series location + dir lock. Folder *naming* token engine is owned by the import/rename area; SER owns the association.

#### Scenario: Default path is derived from the registered root and a safe template

- **WHEN** a series is added against a registered root folder with no explicit path
- **THEN** its stored path is `{root}/{safe series title} ({start_year})`, where the title component is sanitized (no path separators, reserved names, or trailing dots/spaces) from the CV title, and the series folder is created under that root

#### Scenario: Per-series path override must stay under a registered root

- **WHEN** `PUT /api/v1/series/{id}` sets a path that is not under any registered root folder
- **THEN** the request is rejected with a client error and the stored path is unchanged

#### Scenario: A valid path change renames the directory with rollback on failure

- **WHEN** a series' path is changed to a valid location under a registered root
- **THEN** the stored path is updated and the on-disk directory is moved/renamed; if the directory rename fails, the path row change is rolled back so the row and disk stay consistent

### Requirement: FRG-SER-009 — Series statistics

The system SHALL compute per-series statistics — issue count, issue-file count (have/total), size on disk, and next/last release date — via aggregation over issue and issue-file records, exposed on series list and detail resources.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.3 (SeriesResource statistics); mylar-feature-surface.md capability map SER (Have/Total).
- **Notes**: Derived, never stored counters that can drift (fixes Mylar's recount-on-rescan model).

#### Scenario: Statistics aggregate have/total and size on disk

- **WHEN** a series with 10 issues and 4 issue-file rows is fetched via list or detail
- **THEN** the response reports 4/10 (have/total), a non-zero size on disk equal to the sum of its file sizes, and derived next/last release dates

#### Scenario: Statistics update without a manual recount

- **WHEN** a fifth issue-file row is added for that series and it is fetched again
- **THEN** the reported have count is 5/10 and the size on disk grows accordingly, with no recount action invoked

#### Scenario: Statistics are computed per request, not stored

- **WHEN** the schema is inspected and a statistics-bearing response is served
- **THEN** no stored counter columns (issue count, file count, missing count, size) exist; each figure is produced by aggregation at request time

### Requirement: FRG-SER-010 — Per-series disk rescan

The system SHALL provide a per-series rescan command that re-enumerates files under the series path, removes issue-file records whose files vanished, and routes unmatched files through the shared import pipeline.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §5.5 (DiskScanService, shared pipeline); mylar-feature-surface.md capability map SER (forceRescan).
- **Notes**: The import pipeline itself is the IMP/PP area's requirement; SER owns the trigger, cleanup of vanished files, and statistics refresh. Runs automatically after metadata refresh and on demand.

#### Scenario: RescanSeries walks the series path and routes untracked files through the shared pipeline

- **WHEN** RescanSeriesCommand runs for a series and enumerates files under its (possibly overridden) path to a bounded depth using the shared extension list
- **THEN** files already linked to an issue-file record are skipped and every remaining file is routed through the same shared import pipeline used by completed-download handling, with no separate rescan-only import path

#### Scenario: Vanished files are cleared and the issue returns to Wanted

- **WHEN** a file backing an existing issue-file record no longer exists on disk at rescan time
- **THEN** that issue-file record is removed and the now-fileless monitored issue returns to the derived Wanted state

#### Scenario: A correctly named dropped-in file is linked and stats update immediately

- **WHEN** a correctly named file is dropped into the series folder and a rescan is run
- **THEN** the file is matched and a new issue_files row is created, and per-series statistics (have/total, size on disk) reflect the new record immediately via derivation with no manual recount

#### Scenario: Unmatched or blocked files are recorded in a per-series rescan report

- **WHEN** a rescanned file cannot be matched to an issue or is rejected by the shared pipeline
- **THEN** it is recorded in a per-series rescan report with its reason rather than silently ignored, leaving the file in place for the operator to resolve

### Requirement: FRG-SER-011 — Annuals and specials as typed issues

The system SHALL represent annuals and specials as issue records of the parent series with an explicit issue-type field and, where they originate from a distinct ComicVine volume, a stored link to that source volume ID, participating in monitoring, wanted derivation, search, and statistics identically to regular issues.

- **Milestone**: B
- **Source**: mylar-feature-surface.md capability map SER (annuals as first-class linked records); sonarr-architecture.md §1.1 (comic mapping: annuals as issue numbers).
- **Notes**: D2 — deliberate divergence from Mylar's parallel `annuals` table + `ANNUALS_ON` global toggle. Fixes the structured annual/special handling weakness: one lifecycle, one table, typed rows. Discovery/linking of annual volumes is a META concern.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A series with a linked annuals volume shows annuals inline on the series (distinguishable by type), and an unowned monitored annual appears in Wanted.

### Requirement: FRG-SER-012 — Continuing/Ended status maintenance

The system SHALL store series status (continuing/ended) from ComicVine on each refresh and SHALL recalculate it from latest-issue recency when the source is ambiguous, with an optional per-series "force continuing" override that survives refresh.

- **Milestone**: B
- **Source**: mylar-feature-surface.md §8 (Continuing/Ended recalculation <55 days); sonarr-architecture.md §1.1 (SeriesStatusType), §1.2 (ended-series refresh cadence).
- **Notes**: Status feeds the refresh-scheduling skip rules in META. Threshold configurable; Mylar uses 55 days.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A series whose latest issue is older than the recency threshold and not overridden becomes Ended after refresh; a forced-continuing series does not.

### Requirement: FRG-SER-013 — Per-series overrides survive refresh

The system SHALL support per-series user overrides — display/sort title, search aliases (alternate search names), book-type override, and file-naming override — stored separately from source-derived fields so that metadata refresh never clobbers them.

- **Milestone**: B
- **Source**: mylar-feature-surface.md capability map SER (per-series overrides); mylar-comicvine.md §5 (heuristic values user-overridable without refresh clobbering).
- **Notes**: Aliases feed release-title mapping (search area) and pull matching. Provenance (user vs heuristic vs source) is persisted per META heuristic-fields requirement.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Setting a search alias and a book-type override, then forcing a full refresh, leaves both intact while source fields update.

### Requirement: FRG-SER-014 — Series edit and delete

The system SHALL support editing a series' monitored flag, monitoring policy, format profile, root folder/path, and overrides, and deleting a series with an explicit option to also delete its files from disk (default: keep files).

- **Milestone**: M1
- **Source**: mylar-feature-surface.md capability map SER (delete incl. optional folder removal); sonarr-architecture.md §7.1 (Series editor), §5.5 (deletion via recycle bin).
- **Notes**: M1 needs at least monitored-toggle edit and safe delete for a usable browse UI; bulk/mass editor is B (see next).

#### Scenario: Edit updates monitored, policy, profile, and root/path

- **WHEN** `PUT /api/v1/series/{id}` changes monitored, monitor-new-items policy, format profile, and root folder/path (path under a registered root)
- **THEN** the persisted row reflects all changed fields and the detail response returns the updated values

#### Scenario: Default delete removes library rows and keeps files on disk

- **WHEN** `DELETE /api/v1/series/{id}` is called with `deleteFiles=false` (the default)
- **THEN** the series row and its issue and issue-file rows are removed via cascade, while the files remain on disk untouched

#### Scenario: Delete-with-files is explicitly unsupported in M1

- **WHEN** `DELETE /api/v1/series/{id}?deleteFiles=true` is called
- **THEN** the request returns 501 Not Implemented, and no rows are deleted and no files are removed

### Requirement: FRG-SER-015 — Bulk series operations

The system SHALL support bulk operations over a selected set of series: set monitored, change format profile, change root folder (with optional move), and refresh.

- **Milestone**: B
- **Source**: sonarr-architecture.md §7.1 (Series editor/bulk); mylar-feature-surface.md capability map UI (status batch changes).
- **Notes**: Pure convenience layer over the single-series operations; no new domain rules.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Selecting three series and applying "unmonitor" updates all three in one API call.

