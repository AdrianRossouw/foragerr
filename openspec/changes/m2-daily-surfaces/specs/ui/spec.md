# ui — delta for m2-daily-surfaces

## MODIFIED Requirements

### Requirement: FRG-UI-010 — Activity: history screen

The UI SHALL provide a paged history screen of pipeline events with event-type icons, source title, series/issue links, date, and expandable per-event details (indexer, download client, rejection/failure messages), filterable by event type.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §7.4 (Activity/History), §7.3 HistoryResource.
- **Notes**: Lives in the Activity nav group beside Queue. Real server-side pagination (the queue's fixed-page-1 shortcut is not acceptable here — history grows unboundedly); reasons render through the shared verbatim-reasons presentation.

#### Scenario: Grab-and-import cycle renders linked

- **WHEN** the screen loads after one grab→import cycle
- **THEN** both events render with type indicators, the shared downloadId's series/issue links, and dates, newest first; filtering to a different event type hides them

#### Scenario: Expandable details carry verbatim reasons

- **WHEN** the user expands an `import_blocked` event
- **THEN** the per-event data renders (source, provenance) with the rejection reasons verbatim and never re-sorted

#### Scenario: Pagination is real

- **WHEN** more events exist than one page holds
- **THEN** page controls navigate the server-side envelope (per-page query keys), and a new event arriving via WS invalidation appears on page 1

### Requirement: FRG-UI-011 — Wanted screen

The UI SHALL provide a wanted screen listing missing issues (monitored, published, no file) with per-item and select-all automatic search actions and access to interactive search.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §7.4 (Wanted/Missing), §2.4 (searches triggered from Wanted screens).
- **Notes**: Plain missing only — the cutoff-unmet tab is REMOVED with the API's cutoff half (M2 reshape). Per-issue actions reuse the existing interactive-search overlay; search-all enqueues the backlog-search command.

#### Scenario: Derived list with search actions

- **WHEN** a monitored, published, fileless issue exists
- **THEN** it renders with its series link and release date; the row's automatic-search action enqueues an issue search, and its interactive-search action opens the existing overlay scoped to the issue

#### Scenario: Search all covers the listed set

- **WHEN** the user clicks "Search all"
- **THEN** one backlog-search command is enqueued covering the wanted set, and its command status is visible until terminal

#### Scenario: Empty state is explicit

- **WHEN** nothing is missing
- **THEN** the screen says so plainly (distinct from a loading or error state)

### Requirement: FRG-UI-017 — Blocklist screen

The UI SHALL provide a paged blocklist screen showing blocklisted releases (source title, series/issue, indexer, date, reason) with per-item and bulk removal.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §7.4 (Activity/Blocklist), §4.6 blocklist service.
- **Notes**: Thin screen over the new blocklist read/delete API; blocklist WRITE behavior stays DL/SRCH area. Lives in the Activity nav group.

#### Scenario: Banned release visible with reason, removable

- **WHEN** a failed download's release is on the blocklist
- **THEN** it renders with source title, series/issue link, indexer, date, and the ban reason verbatim; removing it deletes the row so the release becomes grabbable again

#### Scenario: Bulk removal

- **WHEN** the user selects several rows and removes them
- **THEN** all selected rows are deleted and the list refreshes; a mid-batch failure reports which removals did not happen

### Requirement: FRG-UI-004 — Series detail screen

The UI SHALL provide a series detail screen showing series metadata (poster, publisher, year, status, overview), the full issue list with per-issue monitored toggle, file presence/format, and per-issue actions (automatic search, interactive search, file deletion), plus series-level actions (refresh, rescan, edit, delete with optional file removal) dispatched via the command endpoint.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.4 (Series details), §7.2 command endpoint; mylar-feature-surface.md §SER (per-series overrides, forceRescan).
- **Notes**: NO reading/preview affordance on issue rows — reader is permanently out of scope; the consumption path is OPDS. m2-daily-surfaces: the delete dialog's "also delete files" option is now real (was an always-501 checkbox), and issue rows with a file gain a delete-file action routed through the recycle bin.

#### Scenario: Banner header renders derived stats and toggles monitored

- **WHEN** the detail screen mounts for a series and the user clicks the header monitored toggle
- **THEN** the banner shows cover, profile, path, and derived stats, and the toggle dispatches a persist request whose new state is reflected in the `['series', id]` cache

#### Scenario: Toolbar action dispatches command and reflects status

- **WHEN** the user clicks Refresh (or Rescan/Search) in the toolbar
- **THEN** a `POST /command` request is issued and the button/area reflects the returned command status as it progresses

#### Scenario: Issue table renders issue numbers as strings with file info

- **WHEN** the issue table renders issues including `1.5` and `1.MU`
- **THEN** those issue numbers render verbatim as strings and issues with a file show their format and size

#### Scenario: Per-row and bulk monitored toggles

- **WHEN** the user toggles a single issue's monitored control, then uses the header checkbox to bulk-toggle
- **THEN** the single toggle persists that issue's state and the header control toggles the monitored state of all selected rows

#### Scenario: Interactive-search button opens the overlay

- **WHEN** the user clicks an issue row's interactive-search button
- **THEN** the interactive search overlay opens scoped to that issue's id

#### Scenario: Deleting an issue file routes through the recycle bin

- **WHEN** the user deletes an issue's file from its row (confirmation required)
- **THEN** the file moves to the recycle bin (or is permanently deleted only when no bin is configured, and the confirmation says so), the issue reverts to file-less (back on Wanted), and a `file_deleted` history event records the action as manual

#### Scenario: Series delete with files is real

- **WHEN** the user deletes a series with "also delete files" checked
- **THEN** every issue file routes through the recycle bin before the series/issue rows are removed — no 501, and unchecking the box preserves files exactly as before
