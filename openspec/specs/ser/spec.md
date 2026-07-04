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

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Adding the same ComicVine volume twice is rejected; a stored series row round-trips all listed fields through the API.

### Requirement: FRG-SER-002 — Issue entity

The system SHALL persist one issue record per ComicVine issue of a watched series, storing ComicVine issue ID, series reference, issue number as a decimal-and-string-safe value (supporting `1`, `1.5`, `1.MU`, `½`), title, cover date, store date, issue type (regular/annual/special/TPB-content), monitored flag, and issue-file reference (null when no file).

- **Milestone**: M1
- **Source**: sonarr-architecture.md §1.1 (Episode entity, comic mapping note on decimal/string issue numbers); mylar-comicvine.md §1.5 (GetIssuesInfo fields).
- **Notes**: No season layer (Sonarr's embedded-season trick shows the middle tier is droppable). Dates are nullable typed fields, never `'0000-00-00'` sentinels (mylar-comicvine.md §3.7).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A series with issues numbered `1`, `1.5`, and an annual imports with all three representable, sortable in reading order, and independently monitorable.

### Requirement: FRG-SER-003 — Two-level monitored flags

The system SHALL provide independent monitored flags at series level and issue level, and SHALL treat an issue as eligible for automatic acquisition only when both its own flag and its series' flag are set.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §1.3 (monitored flags, MonitoredEpisodeSpecification); §8 "two-level monitored flags".
- **Notes**: The single most load-bearing Sonarr behavior per the research doc. Replaces Mylar's per-issue Wanted status writes (D1).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** With the series unmonitored, no monitored issue of it is selected by automatic search; re-monitoring the series restores eligibility without touching issue flags.

### Requirement: FRG-SER-004 — Derived wanted state

The system SHALL compute "wanted" as a derived predicate — series monitored AND issue monitored AND issue released (store/cover date passed or unknown-but-listed) AND no issue file present — and SHALL NOT persist wanted as a stored issue status.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §1.1 ("Wanted/missing is derived"), §8; contrast mylar-feature-surface.md §3 (stored status lifecycle).
- **Notes**: D1. Download-in-flight suppression of re-grabs is the queue/decision engine's job (QueueSpecification analogue), not an issue status.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Importing a file for a wanted issue removes it from the Wanted view with no explicit status write; deleting the file returns it to Wanted.

### Requirement: FRG-SER-005 — Add flow (add → refresh → scan → optional search)

When a series is added, the system SHALL execute a chained sequence: fetch and persist metadata and issues from ComicVine, apply user add-options (root folder, format profile, monitoring strategy, search-on-add), build and validate the series path, scan the path for existing files, and, if requested, queue a search for missing monitored issues — with add-options cleared once the chain completes.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §1.2 (add lifecycle, AddOptions), §8.
- **Notes**: Chain runs as events/commands on the backbone (SCHED area owns the command queue). Path validation includes root-folder existence and slug/path uniqueness (AddSeriesValidator analogue).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Adding a series with "search for missing issues" enabled results in issue records present, existing files matched, and search commands queued, observable via the command/queue API.

### Requirement: FRG-SER-006 — Add-time monitoring strategies

The system SHALL support add-time monitoring strategies of at least: all issues, future issues only, missing issues only, existing issues only, first issue only, and none, applied once during the add flow to set per-issue monitored flags.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §1.3 (MonitorTypes, EpisodeMonitoredService).
- **Notes**: M1 may ship with "all" + "none" wired in UI and the rest API-only; the strategy enum and application service belong to the slice because add-options pass through it. "Pilot"→"first issue" is the comic translation.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Adding the same test series under each strategy yields the documented per-issue monitored pattern.

### Requirement: FRG-SER-007 — Monitor-new-items policy

Each series SHALL carry a monitor-new-items policy (all | none) that determines whether issues newly discovered during metadata refresh are created with their monitored flag set.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §1.1 (MonitorNewItems), §1.2 step 3.
- **Notes**: This is the Sonarr translation of Mylar's `AUTOWANT_UPCOMING` — auto-wanting happens through monitoring policy at refresh time, not through pull-list status writes (D1, D4). PULL requirements depend on this.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** With policy "all", a refresh that discovers a new issue leaves it monitored (hence wanted once released); with "none", it arrives unmonitored.

### Requirement: FRG-SER-008 — Root folders and series paths

The system SHALL support one or more configured root folders; each series SHALL have a path defaulting to `<root folder>/<templated series folder>` created on add, with the folder-name template configurable and the path overridable per series.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §1.2 step 1, §5.5 (RootFolderService); mylar-feature-surface.md capability map SER (multiple destination dirs, create-folders-on-add, per-series location).
- **Notes**: Subsumes Mylar's `MULTIPLE_DEST_DIRS` and per-series location + dir lock. Folder *naming* token engine is owned by the import/rename area; SER owns the association.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Adding a series with no explicit path creates its folder under the chosen root using the template; a per-series path override is honored by import and rescan.

### Requirement: FRG-SER-009 — Series statistics

The system SHALL compute per-series statistics — issue count, issue-file count (have/total), size on disk, and next/last release date — via aggregation over issue and issue-file records, exposed on series list and detail resources.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.3 (SeriesResource statistics); mylar-feature-surface.md capability map SER (Have/Total).
- **Notes**: Derived, never stored counters that can drift (fixes Mylar's recount-on-rescan model).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A series with 10 issues and 4 files reports 4/10 and a non-zero size on disk; importing a fifth file updates the counts without a manual recount action.

### Requirement: FRG-SER-010 — Per-series disk rescan

The system SHALL provide a per-series rescan command that re-enumerates files under the series path, removes issue-file records whose files vanished, and routes unmatched files through the shared import pipeline.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §5.5 (DiskScanService, shared pipeline); mylar-feature-surface.md capability map SER (forceRescan).
- **Notes**: The import pipeline itself is the IMP/PP area's requirement; SER owns the trigger, cleanup of vanished files, and statistics refresh. Runs automatically after metadata refresh and on demand.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Deleting a file on disk then rescanning clears its issue-file record and returns the issue to Wanted; dropping a correctly named file into the folder and rescanning links it.

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

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Deleting a series without the flag leaves files on disk and removes all library records; with the flag, the series folder contents are removed via the recycle-bin mechanism if configured.

### Requirement: FRG-SER-015 — Bulk series operations

The system SHALL support bulk operations over a selected set of series: set monitored, change format profile, change root folder (with optional move), and refresh.

- **Milestone**: B
- **Source**: sonarr-architecture.md §7.1 (Series editor/bulk); mylar-feature-surface.md capability map UI (status batch changes).
- **Notes**: Pure convenience layer over the single-series operations; no new domain rules.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Selecting three series and applying "unmonitor" updates all three in one API call.

