# ser — delta for m4-add-new

## MODIFIED Requirements

### Requirement: FRG-SER-005 — Add flow (add → refresh → scan → optional search)

When a series is added, the system SHALL execute a chained sequence: fetch and persist metadata and issues from ComicVine, apply user add-options (root folder, format profile, monitoring strategy, search-on-add, and an optional explicit collected-edition book-type per FRG-SER-018), build and validate the series path, scan the path for existing files, and, if requested, queue a search for missing monitored issues — with add-options cleared once the chain completes.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §1.2 (add lifecycle, AddOptions), §8.
- **Notes**: Chain runs as events/commands on the backbone (SCHED area owns the command queue). Path validation includes root-folder existence and slug/path uniqueness (AddSeriesValidator analogue). m4-add-new: the optional book-type add-option feeds FRG-SER-018's override/lock mechanics; omitted, derivation behaves exactly as before.

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

### Requirement: FRG-SER-018 — Series collected-edition (trade) typing

The system SHALL type a series by its collected-edition **book-type**: a nullable
`booktype` on the series drawn from the existing parser `Booktype` vocabulary
(`tpb` / `gn` / `hc` / `one_shot`; null = an ordinary single-issues run). The book-type
SHALL be **auto-derived** from the series title at add and at refresh using the existing
`BOOKTYPE_CUES` (the same cues the filename parser uses); a series whose title carries
no collected-edition cue is typed null. The operator SHALL be able to set the book-type
explicitly — at add time via an optional add-option, or later on the series — in which
case it is **locked** (`booktype_locked`) so a later
`refresh-series` does not re-derive over the operator's choice (mirroring the
grouping-override precedent, FRG-SER-017); clearing the lock returns it to
auto-derivation. An explicit single-issues choice (null book-type) locks the same way.
Typing is additive display metadata: it SHALL NOT change series
identity, monitoring, wanted state, or matching. The filename-derived `{Booktype}`
naming token is unaffected — series-level typing does not itself drive file naming (a
series-typed naming default is out of scope; see the proposal's Non-goals).

#### Scenario: Collected-edition title is auto-typed

- **WHEN** a series titled with a collected-edition cue ("… TPB", "… (Graphic Novel)") is added or refreshed and the operator has not locked its book-type
- **THEN** its `booktype` is derived from the cue (tpb/gn/hc), while a single-issues run with no cue is typed null, and neither series' identity/monitoring/wanted state changes

#### Scenario: Operator book-type override survives refresh

- **WHEN** the operator sets a series' book-type explicitly and a later `refresh-series` runs
- **THEN** the operator's book-type persists (it is locked, not re-derived); clearing the lock re-derives on the next refresh

#### Scenario: Add-time explicit book-type is honored and locked

- **WHEN** a series is added with an explicit book-type add-option (a collected-edition value, or an explicit single-issues/null choice)
- **THEN** the series persists that book-type locked — title-cue derivation is skipped at add and at later refreshes until the lock is cleared — and an add without the option derives exactly as before
