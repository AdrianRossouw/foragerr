# ser — delta for m11-acquisition-responsiveness

## MODIFIED Requirements

### Requirement: FRG-SER-005 — Add flow (add → refresh → scan → search)

When a series is added, the system SHALL execute a chained sequence: fetch and persist metadata and issues from ComicVine, apply user add-options (root folder, format profile, monitoring strategy, search-on-add, and an optional explicit collected-edition book-type per FRG-SER-018), build and validate the series path, scan the path for existing files, and queue a bounded search for the series' missing monitored issues — by default for any add whose monitoring yields wanted issues, and always when search-on-add was requested — with add-options cleared once the chain completes.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §1.2 (add lifecycle, AddOptions), §8.
- **Notes**: Chain runs as events/commands on the backbone (SCHED area owns the command queue). Path validation includes root-folder existence and slug/path uniqueness (AddSeriesValidator analogue). m4-add-new: the optional book-type add-option feeds FRG-SER-018's override/lock mechanics; omitted, derivation behaves exactly as before. m11: the default sweep closes the fresh-install first-sweep gap (a newly added monitored series acquires without waiting for the backlog tick); the sweep is the same per-series bounded SeriesSearchCommand the checkbox path always used, and command dedup collapses the pair when both fire.

#### Scenario: Add validates before persisting

- **WHEN** `POST /api/v1/series` is called with a non-existent CV volume, an unregistered root folder, or a duplicate `cv_volume_id`
- **THEN** the request is rejected with a client error and no series row, command, or path is created

#### Scenario: A successful add enqueues the chain as separate commands visible in job history

- **WHEN** a valid series is added
- **THEN** the series row is persisted carrying its `add_options`, and a `RefreshSeriesCommand` for the series is enqueued on the persisted command backbone, each subsequent step (`ScanSeriesCommand`, and `SeriesSearchCommand`) appearing as its own entry observable via the command/job-history API

#### Scenario: The chain populates issues, matches files, and clears add-options

- **WHEN** the add chain runs to completion for a series added with existing files under its path
- **THEN** issue records are present, existing on-disk files are matched to issue-file rows by the parser, `add_options` is cleared on the series row, and the sequence is restart-safe (an interrupted chain resumes from the persisted queue rather than restarting the add)

#### Scenario: The default mini-sweep fires for a monitored add

- **WHEN** a series is added with a monitoring strategy that yields wanted issues and search-on-add unchecked
- **THEN** a `SeriesSearchCommand` for that series is enqueued after the scan step, bounded to the series' wanted issues, recorded in job history with real dedup semantics, and observable via the command API

#### Scenario: A no-wanted add stays quiet

- **WHEN** a series is added with a monitoring strategy that yields no wanted issues (e.g. monitor none) and search-on-add unchecked
- **THEN** no search command is enqueued

#### Scenario: Importing an existing library never sweeps

- **WHEN** the Library Import flow creates series for groups of files already on disk (each about to be imported)
- **THEN** no default search sweeps are enqueued for those series — the sweep exists for the operator's add intent, and a thousand-group import must not race a thousand searches against its own imports
