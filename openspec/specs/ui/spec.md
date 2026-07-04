# UI — Web Frontend Specification

## Purpose

Baseline requirements for web frontend, mined from the
Phase 1 reference research (`docs/research/`). Baseline depth per the Phase 2 scope
decision: SHALL + coarse acceptance; scenario-level elaboration happens in the
milestone change that implements each requirement (FRG-PROC-003, FRG-PROC-009).

## Requirements

### Requirement: FRG-UI-001 — SPA architecture: server state via React Query + WS invalidation

The frontend SHALL be a React + TypeScript single-page application in which all server state is managed by React Query with query keys mirroring API paths, local UI state kept in a small client store, and a single WebSocket listener component that maps resource-change messages onto React Query cache invalidations/patches.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.4 frontend ("that exact trio... is the recommended foragerr frontend architecture"), §6.2 UI push.
- **Notes**: Architecture requirement — everything else in UI assumes it. Depends on API WebSocket requirement.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** With the app open, a queue change pushed over WS updates the queue screen without user-triggered refetch; no component maintains its own copy of server data outside React Query.

### Requirement: FRG-UI-002 — Design token layer with ant/foraging theme

All UI styling SHALL be driven by a central design-token layer (colors, typography, spacing, iconography) in which the ant/foraging brand theme is expressed once as token values, such that no screen-level component hardcodes brand colors or theme-specific styling.

- **Milestone**: M1
- **Source**: Assignment guidance (ant/foraging theme as a design-token requirement, not per-screen styling); sonarr-architecture.md §7.4 (screen inventory the tokens apply across).
- **Notes**: Deliberately scoped as one requirement so theming never appears again per-screen. Token names should be theme-neutral (e.g. `--color-accent`, not `--ant-orange`).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Changing the primary accent token in one place restyles all screens; a grep of screen components finds no hardcoded brand color literals.

### Requirement: FRG-UI-003 — Library index screen

The UI SHALL provide a library index screen listing all series with poster art, title, monitored state, and have/total issue counts, supporting at minimum sort (title, date added) and a text filter, with poster and table view modes.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.4 (Series index); mylar-feature-surface.md UI section (watchlist index, alpha index).
- **Notes**: "UI browse" leg of the vertical slice. Advanced filtering (publisher, status, tags) is M2 polish under this same screen — do not split into separate requirements.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A library of 50+ series renders with posters, can be sorted by title and filtered by substring, and clicking a series opens its detail screen.

### Requirement: FRG-UI-004 — Series detail screen

The UI SHALL provide a series detail screen showing series metadata (poster, publisher, year, status, overview), the full issue list with per-issue monitored toggle, file presence/format, and per-issue actions (automatic search, interactive search), plus series-level actions (refresh, rescan, edit, delete with optional folder removal) dispatched via the command endpoint.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.4 (Series details), §7.2 command endpoint; mylar-feature-surface.md §SER (per-series overrides, forceRescan).
- **Notes**: NO reading/preview affordance on issue rows — reader is permanently out of scope; the consumption path is OPDS. Per-series overrides (alternate search names, etc.) are M2 fields on this screen.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** From a series page, toggling an issue's monitored flag persists; triggering an issue search creates a visible command; an issue with a file shows its format and size.

### Requirement: FRG-UI-005 — Add-series search screen

The UI SHALL provide an add-series screen where the user searches ComicVine by title (or pastes a ComicVine volume id/URL), sees candidate volumes with poster, year, publisher, and issue count, and adds one with root folder, monitoring strategy, and format-profile selections.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.4 (AddSeries lookup), §1.2 add flow; mylar-feature-surface.md §SER (add by CV search or CV ID).
- **Notes**: First leg of the vertical slice. "Import existing library" mass-add flow is a separate M2 requirement below — keep them distinct.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Searching a known title, selecting a result, and adding it lands the series in the library index and kicks off the refresh chain (visible as a command).

### Requirement: FRG-UI-006 — Activity: queue screen

The UI SHALL provide a queue screen rendering the tracked-download queue live (WS-driven): title, series/issue, progress (size/sizeleft), state, warning/error status with expandable status messages, estimated completion, and per-item remove (with delete-data and blocklist options).

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.4 (Activity/Queue), §4.4-4.5 tracked download states; API queue requirement.
- **Notes**: "Queue tracking" leg of the slice. ImportBlocked resolution routes to the manual-import overlay (M2) — in M1 it may only display the blocked reason.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Grabbing a release makes it appear on the queue without reload, progress advances, and it leaves the queue on import; an ImportBlocked item visibly demands attention with its messages.

### Requirement: FRG-UI-007 — Interactive search overlay

The UI SHALL provide an interactive search overlay (launchable from series detail and wanted screens) listing every release decision from `GET /release` — including rejected ones with their reasons — with columns for indexer, title, size, age, format, and score, and a grab button per approved/overridable row.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §2.4 (interactive search returns all decisions), §7.2 release endpoint, §7.4 InteractiveSearch overlay.
- **Notes**: This is the primary explainability surface for the decision engine — rejection reasons must be shown verbatim, not summarized.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** An interactive search shows at least one rejected release with a human-readable reason; grabbing an approved row sends it to the queue.

### Requirement: FRG-UI-008 — Settings: indexers with schema-driven forms and test buttons

The UI SHALL provide an indexer settings screen that renders add/edit forms entirely from `GET /indexer/schema` field metadata (no per-implementation frontend code), including per-indexer RSS/automatic/interactive toggles, priority, and categories, with a Test button invoking `POST /indexer/test` and surfacing structured pass/fail.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.2 provider schema pattern, §2.1/§2.3 Newznab settings; mylar-feature-surface.md §UI (provider tests).
- **Notes**: The generic schema-form renderer built here is reused verbatim for download clients (M1) and notifiers (M2) — build it once, generically.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Adding a Newznab indexer via the generated form with a bad API key fails the test with a message; with a good key it saves and appears enabled.

### Requirement: FRG-UI-009 — Settings: download clients

The UI SHALL provide a download-client settings screen using the same schema-driven form renderer for SABnzbd (and later the built-in DDL client), including category, priority, and remove-completed options, with a working Test button.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §4.1-4.2 SABnzbd client settings, §7.2 schema pattern; mylar-feature-surface.md §DL.
- **Notes**: DDL client appears here automatically once its backend implementation registers in the schema — no new UI requirement needed for it.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Configuring SABnzbd with host/API key/category passes test and subsequent grabs appear in SAB under the configured category.

### Requirement: FRG-UI-010 — Activity: history screen

The UI SHALL provide a paged history screen of pipeline events with event-type icons, source title, series/issue links, date, and expandable per-event details (indexer, download client, rejection/failure messages), filterable by event type.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §7.4 (Activity/History), §7.3 HistoryResource.
- **Notes**: Depends on API history endpoint (M2).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** After one grab→import cycle the screen shows both events linked to the same series/issue; filtering to "failed" hides them.

### Requirement: FRG-UI-011 — Wanted screen

The UI SHALL provide a wanted screen listing missing issues (monitored, published, no file) with per-item and select-all automatic search actions and access to interactive search.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §7.4 (Wanted/Missing), §2.4 (searches triggered from Wanted screens).
- **Notes**: Cutoff-unmet tab arrives with format-profile cutoffs (B if profiles are late).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A monitored, fileless issue appears; "Search all" enqueues a search command covering the listed issues.

### Requirement: FRG-UI-012 — Settings: media management and naming with rename preview

The UI SHALL provide media-management/naming settings (rename on/off, folder and file templates with token help, illegal-character policy, root folders) with a live preview showing example output for the current template and a per-series rename preview (existing → new paths) before execution.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §5.4 naming engine ("Rename is previewable"), §7.1 Config/naming; mylar-feature-surface.md §PP (FILE_FORMAT/FOLDER_FORMAT tokens).
- **Notes**: M1 renames with the default template and no settings screen; this requirement is the configurability layer. Token vocabulary is defined by the import/naming area — UI renders its help from one shared definition.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Editing the file template updates the example filename; the rename preview for a series lists old→new diffs and applies only on confirm.

### Requirement: FRG-UI-013 — Settings: notifications

The UI SHALL provide a notification settings screen using the schema-driven form renderer, with per-connection event-opt-in checkboxes (on grab, on import, on upgrade, on failure, on health issue) and a Test button per connection.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §7.2 schema pattern; mylar-feature-surface.md §6 / §NOTIF (per-agent opt-in gates, test endpoints).
- **Notes**: Pure consumer of the NOTIF area's provider schema — ships in the same milestone as the NOTIF core.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Adding a Discord webhook, enabling only "on import", and pressing Test delivers a test message; a grab then produces no notification but an import does.

### Requirement: FRG-UI-014 — Manual import overlay

The UI SHALL provide a manual-import overlay (reachable from ImportBlocked queue items and from a path picker) listing candidate files with their would-be decisions and rejection reasons, allowing per-file override of series, issue, and format before importing.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §5.5 manual import, §4.5 ImportBlocked → ManualInteractionRequiredEvent, §7.4 InteractiveImport overlay.
- **Notes**: Depends on API manual-import endpoint (M2). Also serves the "import existing library" flow below.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** An ImportBlocked download is resolvable end-to-end from the queue screen via the overlay, landing the file in the library.

### Requirement: FRG-UI-015 — Library import (existing files) flow

The UI SHALL provide a library-import flow that scans a chosen root folder for unmapped series folders, proposes ComicVine matches per folder, and lets the user confirm/correct matches before bulk-adding series with their existing files imported in place.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §5.5 (RootFolderService unmapped-folder enumeration feeding "import existing library" UI), §7.4 (AddSeries library import); mylar-feature-surface.md §IMP.
- **Notes**: Backend scanning/matching is IMP area. Mylar's importresults staging UI is the ancestor; Sonarr's folder-level flow is the shape to copy.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Pointing the flow at a folder of pre-existing comics adds matched series whose issues show hasFile without any download.

### Requirement: FRG-UI-016 — System status and tasks screens

The UI SHALL provide system screens showing application status (version, paths, runtime), current health warnings with remediation hints, and the scheduled-task table (last/next run) with per-task force-run buttons.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §7.4 (System/{Status, Tasks}), §7.1 Health; mylar-feature-surface.md §SCHED (force-run from UI, jobhistory).
- **Notes**: Log viewer screen is B — server-side log files suffice for a single-admin private tool until then.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A failing indexer's health warning is visible; force-running the RSS task updates its last-run timestamp.

### Requirement: FRG-UI-017 — Blocklist screen

The UI SHALL provide a paged blocklist screen showing blocklisted releases (source title, series/issue, indexer, date, reason) with per-item and bulk removal.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §7.4 (Activity/Blocklist), §4.6 blocklist service.
- **Notes**: Thin screen over the blocklist API; blocklist behavior itself is DL/SRCH area.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A failed download's release appears on the blocklist and can be removed so it becomes grabbable again.

### Requirement: FRG-UI-018 — Weekly pull / calendar view

The UI SHALL provide a release-calendar or weekly-pull view of upcoming/recent issues for watched series with want/skip actions per entry.

- **Milestone**: B
- **Source**: mylar-feature-surface.md §1 weekly pull + §PULL capability map; sonarr-architecture.md §7.1 Calendar (+iCal).
- **Notes**: Backend is PULL area (not in this baseline) — this UI requirement is deliberately B and blocked on PULL; recorded here so the screen inventory is complete. Choose Mylar pull-list shape vs Sonarr calendar shape at PULL design time.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A watched series with an issue shipping this week shows it in the view; marking it wanted feeds the search pipeline.

