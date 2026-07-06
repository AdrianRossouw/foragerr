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

#### Scenario: Query keys mirror API resource paths

- **WHEN** the series index, a series detail, a queue page, and a release list mount and issue their fetches
- **THEN** the queries are registered under keys `['series']`, `['series', id]`, `['queue', page]`, and `['release', issueId]` respectively, each backed by exactly one network request whose URL path corresponds to the key

#### Scenario: WebSocketBridge maps messages to cache invalidation

- **WHEN** the single `<WebSocketBridge>` receives a `{name, action, resource}` message for the `series` resource while a `['series']` query is cached
- **THEN** it invalidates the matching React Query cache entry and a refetch of `['series']` is observed, with no manual refetch call in any screen component

#### Scenario: Queue progress patched without refetch

- **WHEN** a queue-progress message arrives for an item currently in the `['queue', page]` cache
- **THEN** the bridge patches the cached queue entry in place (updated progress rendered) and no new `/api/v1/queue` request is issued for that patch

#### Scenario: Reconnect with backoff and sidebar connection state

- **WHEN** the WebSocket connection drops and then is re-established
- **THEN** the sidebar footer renders a disconnected state, reconnection attempts occur on an increasing backoff interval, and on success the footer renders a connected state; no component holds server data in a store outside React Query

### Requirement: FRG-UI-002 — Design token layer with ant/foraging theme

All UI styling SHALL be driven by a central design-token layer (colors, typography, spacing, iconography) in which the ant/foraging brand theme is expressed once as token values, such that no screen-level component hardcodes brand colors or theme-specific styling.

- **Milestone**: M1
- **Source**: Assignment guidance (ant/foraging theme as a design-token requirement, not per-screen styling); sonarr-architecture.md §7.4 (screen inventory the tokens apply across).
- **Notes**: Deliberately scoped as one requirement so theming never appears again per-screen. Token names should be theme-neutral (e.g. `--color-accent`, not `--ant-orange`).

#### Scenario: Tokens defined once with theme-neutral names

- **WHEN** `src/theme/tokens.css` is loaded and its custom properties are enumerated
- **THEN** tokens such as `--color-accent`, `--surface-*`, and `--spacing-*` are defined with Sonarr-dark default values, and the accent token resolves to the ant brand color value

#### Scenario: Changing the accent token restyles all screens

- **WHEN** the value of `--color-accent` is overridden at `:root`
- **THEN** rendered screen components that use accent styling reflect the new computed color, with no screen component hardcoding a brand color literal

#### Scenario: Token-name audit rejects brand-named tokens

- **WHEN** the token-name audit test enumerates every custom property name in `tokens.css`
- **THEN** the assertion passes only if no token name matches `ant-` or any brand-specific naming, failing the build otherwise

### Requirement: FRG-UI-003 — Library index screen

The UI SHALL provide a library index screen listing all series with poster art, title, monitored state, and have/total issue counts, supporting at minimum sort (title, date added) and a text filter, with poster and table view modes.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.4 (Series index); mylar-feature-surface.md UI section (watchlist index, alpha index).
- **Notes**: "UI browse" leg of the vertical slice. Advanced filtering (publisher, status, tags) is M2 polish under this same screen — do not split into separate requirements.

#### Scenario: Poster grid renders from local cover endpoint

- **WHEN** the index renders a mocked library of 50+ series in poster mode
- **THEN** each card shows the title, monitored state, and have/total counts, and every poster `img` `src` points at the local cover endpoint (no external ComicVine image host)

#### Scenario: View-mode toggle switches poster and table

- **WHEN** the user activates the table view toggle from poster view
- **THEN** the series render as table rows with title/count/have columns, and toggling back restores the poster grid

#### Scenario: Toolbar sort and text filter

- **WHEN** the user sorts by title and types a substring into the filter box
- **THEN** the rendered series order reflects the chosen sort and only series whose title contains the substring remain visible

#### Scenario: Selecting a series opens detail

- **WHEN** the user clicks a series card
- **THEN** navigation to that series' detail route occurs (asserted via router location / detail heading)

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

### Requirement: FRG-UI-005 — Add-series search screen

The UI SHALL provide an add-series screen where the user searches ComicVine by title (or pastes a ComicVine volume id/URL), sees candidate volumes with poster, year, publisher, and issue count, and adds one with root folder, monitoring strategy, and format-profile selections. The screen SHALL distinguish the non-success search outcomes — a lookup error (including ComicVine credential failure, classified by the API's machine-readable field discriminator and rendered with guidance to check Settings), an incomplete result (degraded walk), a capped result (advising a narrower search), and a genuinely empty result — never rendering an error, degraded, or capped outcome as plain "no results", rendering exactly one outcome state at a time, and always honouring a re-submitted search (a same-term retry issues a fresh lookup rather than serving the failed or degraded result from cache).

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.4 (AddSeries lookup), §1.2 add flow; mylar-feature-surface.md §SER (add by CV search or CV ID).
- **Notes**: First leg of the vertical slice. "Import existing library" mass-add flow is a separate M2 requirement below — keep them distinct. Outcome-state distinction added in m2-lookup-error-surfacing: a missing/invalid ComicVine key previously rendered as "no results".

#### Scenario: Search renders CV candidates with plausibility annotations

- **WHEN** the user types a title and the ComicVine lookup returns candidates
- **THEN** each candidate renders poster, year, publisher, and issue count, and any plausibility annotations returned are rendered on the candidate

#### Scenario: Credential failure renders an actionable error, not empty results

- **WHEN** the lookup request fails because the ComicVine API key is missing or invalid
- **THEN** the screen renders an error state that names the ComicVine API key as the likely cause and points the user at Settings — the empty "no results" presentation is not shown

#### Scenario: Incomplete results are flagged; clean empty stays plain

- **WHEN** the lookup succeeds but the response is marked incomplete
- **THEN** any returned candidates render along with a notice that results may be incomplete and a retry may recover the rest; a degraded response with ZERO candidates renders as a lookup failure (error styling, retry guidance), not as a mild footnote; a complete response with zero candidates renders the plain "no results" state

#### Scenario: Capped results advise narrowing, not retrying

- **WHEN** the lookup response is marked truncated (the deliberate result cap was hit)
- **THEN** the returned candidates render with a notice that the result set was capped and the search should be narrowed — not the transient "retry" incomplete wording

#### Scenario: Re-searching the same term retries for real

- **WHEN** a previous search for a term ended in an error, an incomplete result, or a capped result, and the user submits the same term again
- **THEN** a fresh lookup request is issued (the failed/degraded outcome is not served from cache), so recovering after fixing the API key or after a ComicVine hiccup requires no term perturbation

#### Scenario: Add panel exposes required add options

- **WHEN** the user selects a candidate
- **THEN** the add panel renders controls for root folder, format profile, monitor strategy, and search-on-add

#### Scenario: Adding navigates to detail with refresh command visible

- **WHEN** the user confirms the add
- **THEN** the app navigates to the new series' detail route and a refresh command is visible as in-progress on that screen

### Requirement: FRG-UI-006 — Activity: queue screen

The UI SHALL provide a queue screen rendering the tracked-download queue live (WS-driven): title, series/issue, progress (size/sizeleft), state, warning/error status with expandable status messages, estimated completion, and per-item remove (with delete-data and blocklist options).

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.4 (Activity/Queue), §4.4-4.5 tracked download states; API queue requirement.
- **Notes**: "Queue tracking" leg of the slice. ImportBlocked resolution routes to the manual-import overlay (M2) — in M1 it may only display the blocked reason.

#### Scenario: Queue table renders from the queue endpoint

- **WHEN** the queue screen mounts against `/api/v1/queue`
- **THEN** each row renders title, series/issue, a status chip, progress, and size/remaining derived from the response

#### Scenario: WS progress advances rows without reload

- **WHEN** a WS progress message arrives for a queued item
- **THEN** that row's progress updates in place with no new `/api/v1/queue` fetch, and an item that reaches import leaves the table

#### Scenario: Import-blocked chip exposes reason popover

- **WHEN** a row has status `import_pending` or `import_blocked`
- **THEN** its status chip renders the blocked/pending variant and activating it reveals a popover containing the reason text

#### Scenario: Remove dialog offers blocklist option

- **WHEN** the user clicks remove on a queue item
- **THEN** a dialog appears with delete-data and blocklist options, and confirming issues the corresponding remove request

### Requirement: FRG-UI-007 — Interactive search overlay

The UI SHALL provide an interactive search overlay (launchable from series detail and wanted screens) listing every release decision from `GET /release` — including rejected ones with their reasons — with columns for indexer, title, size, age, format, and score, and a grab button per approved/overridable row.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §2.4 (interactive search returns all decisions), §7.2 release endpoint, §7.4 InteractiveSearch overlay.
- **Notes**: This is the primary explainability surface for the decision engine — rejection reasons must be shown verbatim, not summarized.

#### Scenario: Overlay lists approved and rejected decisions in comparator order

- **WHEN** the overlay opens against `/api/v1/release?issueId=<id>` returning a mix of approved and rejected releases
- **THEN** every decision renders as a row (both approved and rejected) with indexer, size, age, and score columns, in the same order the endpoint returned them

#### Scenario: Rejection reasons shown verbatim

- **WHEN** a rejected row's reason affordance is expanded/hovered
- **THEN** the full list of rejection reasons renders verbatim (not summarized), one per reason returned

#### Scenario: Grab posts the cache key for an approved row

- **WHEN** the user clicks the grab button on an approved row
- **THEN** a POST carrying that release's cache key is issued (approved-only rows expose the button)

#### Scenario: Expired-cache grab surfaces the search-again error

- **WHEN** a grab targets a cache key the backend reports as expired
- **THEN** the overlay renders the deterministic search-again error message

### Requirement: FRG-UI-008 — Settings: indexers with schema-driven forms and test buttons

The UI SHALL provide an indexer settings screen that renders add/edit forms entirely from `GET /indexer/schema` field metadata (no per-implementation frontend code), including per-indexer RSS/automatic/interactive toggles, priority, and categories, with a Test button invoking `POST /indexer/test` and surfacing structured pass/fail.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.2 provider schema pattern, §2.1/§2.3 Newznab settings; mylar-feature-surface.md §UI (provider tests).
- **Notes**: The generic schema-form renderer built here is reused verbatim for download clients (M1) and notifiers (M2) — build it once, generically.

#### Scenario: Provider cards with enable toggles

- **WHEN** the indexer settings screen renders configured providers
- **THEN** each provider appears as a card with an enable toggle whose state reflects the provider's enabled flag

#### Scenario: Add/edit modal rendered generically from schema field metadata

- **WHEN** the add/edit modal opens using `GET /indexer/schema` field metadata containing text, number, select, checkbox, and password fields
- **THEN** each field renders via the widget map to its matching input type, and secret (password) fields render write-only with a placeholder rather than the stored value

#### Scenario: Test button surfaces field-precise failures

- **WHEN** the user clicks Test and `POST /indexer/test` returns a per-field failure
- **THEN** the failure message is rendered against the specific field it concerns

#### Scenario: Valid config saves and card shows enabled

- **WHEN** a valid indexer configuration passes test and is saved
- **THEN** the provider card renders in the enabled state

### Requirement: FRG-UI-009 — Settings: download clients

The UI SHALL provide a download-client settings screen using the same schema-driven form renderer for SABnzbd (and later the built-in DDL client), including category, priority, and remove-completed options, with a working Test button.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §4.1-4.2 SABnzbd client settings, §7.2 schema pattern; mylar-feature-surface.md §DL.
- **Notes**: DDL client appears here automatically once its backend implementation registers in the schema — no new UI requirement needed for it.

#### Scenario: Same generic renderer drives download-client forms

- **WHEN** the download-client add/edit modal opens against `GET /downloadclient/schema`
- **THEN** the form is produced by the identical generic renderer component used for indexers, with no download-client-specific form code, rendering category, priority, and remove-completed fields from the schema

#### Scenario: Test button hits the download-client test endpoint

- **WHEN** the user clicks Test on a download-client form
- **THEN** `POST /downloadclient/test` is invoked and its structured pass/fail result is rendered, including any field-precise failure

#### Scenario: Secret fields remain write-only

- **WHEN** a SABnzbd configuration with an API key field is edited
- **THEN** the API key field renders write-only with a placeholder and the stored secret is not emitted into the DOM

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

### Requirement: FRG-UI-012 — Settings: media management and naming with rename preview

The UI SHALL provide media-management/naming settings (rename on/off, folder and file templates with token help, illegal-character policy, root folders) with a live preview showing example output for the current template and a per-series rename preview (existing → new paths) before execution.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §5.4 naming engine ("Rename is previewable"), §7.1 Config/naming; mylar-feature-surface.md §PP (FILE_FORMAT/FOLDER_FORMAT tokens); docs/research/sonarr-ui §10 (media-management screen: monospace template inputs, live "Example:" line, `?` token popover, save-bar model).
- **Notes**: Bespoke single-form settings page (not the provider list+modal machinery), reusing the `components/schemaForm/SchemaForm` field renderer for standard fields plus two bespoke panels — the live example preview and the per-series rename-preview table (design decision 11). Token help renders from one shared vocabulary (`renamer._TOKEN_ALIASES`). Field errors reuse the `settings.`-prefix `mapApiError` mapping. m2-daily-surfaces: the requirement text always promised root folders on this page; the shipped screen omitted them entirely (a fresh install had NO way to register one) — the Root Folders section is now mandatory.

#### Scenario: Root folders are manageable from settings

- **WHEN** the Media Management page renders
- **THEN** a Root Folders section lists registered roots with free space, adds a new root by path (validation errors from the API render against the input verbatim), and removes an unreferenced root after confirmation — a root still referenced by series shows the refusal reason instead of deleting

#### Scenario: First run points at root-folder setup

- **WHEN** no root folder is registered and the user opens Add Series or Library Import
- **THEN** the root-folder-required state links to the Media Management settings section where one can actually be created (no dead end)

#### Scenario: Live example recomputes as the template is edited

- **GIVEN** the media-management settings page open on a fixture series
- **WHEN** the user edits the file template
- **THEN** the example filename shown under the input recomputes live from the shared token vocabulary without a round-trip to save.

#### Scenario: Per-series rename preview applies only on confirm

- **GIVEN** a series with library files whose names differ from the current template
- **WHEN** the user opens the rename preview
- **THEN** the panel lists old→new diffs, no filesystem change occurs until the user confirms, and confirming invokes the execute endpoint.

#### Scenario: Token help popover from the shared vocabulary

- **GIVEN** the `?` affordance beside a template input
- **WHEN** it is activated
- **THEN** a token cheatsheet renders every supported token from the one shared definition (no hand-maintained duplicate list).

#### Scenario: Standard fields render via SchemaForm and persist on save

- **GIVEN** the page's rename toggle, illegal-character policy, transfer mode, import mode, and recycle-bin path + retention fields
- **WHEN** the user changes one and uses the save-bar
- **THEN** the field is rendered by the shared `SchemaForm` renderer and the change persists through the config `PUT` endpoint.

#### Scenario: Field-precise validation error attaches to its field

- **GIVEN** an invalid submission (e.g. a blank template or a non-confinable recycle-bin path)
- **WHEN** save returns a field-precise 4xx in the uniform error shape
- **THEN** the error is displayed against the offending field via the `settings.`-prefix `mapApiError` mapping, not as a bare form error.

### Requirement: FRG-UI-013 — Settings: notifications

The UI SHALL provide a notification settings screen using the schema-driven form renderer, with per-connection event-opt-in checkboxes (on grab, on import, on upgrade, on failure, on health issue) and a Test button per connection.

- **Milestone**: B
- **Source**: sonarr-architecture.md §7.2 schema pattern; mylar-feature-surface.md §6 / §NOTIF (per-agent opt-in gates, test endpoints).
- **Notes**: Pure consumer of the NOTIF area's provider schema — ships in the same milestone as the NOTIF core.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Adding a Discord webhook, enabling only "on import", and pressing Test delivers a test message; a grab then produces no notification but an import does.

### Requirement: FRG-UI-014 — Manual import overlay

The UI SHALL provide a manual-import overlay (reachable from ImportBlocked queue items and from a path picker) listing candidate files with their would-be decisions and rejection reasons, allowing per-file override of series, issue, and format before importing.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §5.5 manual import, §4.5 ImportBlocked → ManualInteractionRequiredEvent, §7.4 InteractiveImport overlay.
- **Notes**: Depends on the API manual-import endpoint. Design-school reference is `InteractiveSearchOverlay` (Modal, decision chip + Popover of verbatim reasons, no client-side re-sorting).

#### Scenario: Reachable from an ImportBlocked queue row

- **WHEN** the user opens "Manual import" on an `import_blocked` queue row
- **THEN** the overlay opens for that download, lists its candidate files with decision chips and verbatim rejection reasons, and imports the file end-to-end into the library once a valid override is applied.

#### Scenario: Reachable from a path picker

- **WHEN** the user opens manual import via the path picker and selects a folder
- **THEN** the overlay lists that folder's archives with their would-be decisions and per-file override controls.

#### Scenario: Per-file override controls, pre-filled

- **WHEN** a candidate row renders
- **THEN** it shows series/issue/format controls pre-filled from the API's suggested values; the issue picker is scoped to the chosen series; and a verified embedded ComicInfo suggestion is badged as such.

#### Scenario: Verbatim reasons for blocked rows

- **WHEN** a candidate's would-be decision is blocked
- **THEN** its reasons render verbatim (as returned) via the decision popover — never paraphrased or re-ordered client-side.

#### Scenario: Submit and reflect outcome

- **WHEN** the user imports the selected files
- **THEN** the overlay posts the corrected mappings, and on completion the imported files leave the list while any still-blocked files re-render with their updated reasons; the queue view refreshes.

### Requirement: FRG-UI-015 — Library import (existing files) flow

The UI SHALL provide a library-import flow that scans a chosen root folder for unmapped series folders, proposes ComicVine matches per folder, and lets the user confirm/correct matches before bulk-adding series with their existing files imported in place.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §5.5 (RootFolderService unmapped-folder enumeration feeding "import existing library" UI), §7.4 (AddSeries library import); mylar-feature-surface.md §IMP.
- **Notes**: Backend scanning/matching is IMP area. Mylar's importresults staging UI is the ancestor; Sonarr's folder-level flow is the shape to copy. The scan runs as a command (WS command-status invalidation drives progress, as the manual-import overlay does); match correction reuses the existing ComicVine lookup; bulk-add reuses the add-options pieces (root folder, format profile, monitor strategy) applied once for the whole batch with per-group opt-out.

#### Scenario: Scan and review proposed matches

- **WHEN** the user opens Library Import, picks a configured root folder, and starts a scan
- **THEN** a running state is visible until the scan command completes, then staged groups render — folder name, file count, parse confidence, and the proposed ComicVine match (poster, name, year, publisher) or an explicit no-match state — with nothing imported yet

#### Scenario: Correcting a match before import

- **WHEN** the user rejects a proposed match on a group and searches ComicVine inline
- **THEN** the group updates to the chosen volume and is marked user-confirmed; groups with no plausible match require this explicit choice before they can be selected for import

#### Scenario: Bulk-add applies batch options and shows per-group outcomes

- **WHEN** the user selects groups, sets batch add options (root folder is the scanned one; format profile, monitor strategy), and confirms the import
- **THEN** each selected group becomes a series whose existing files import through the shared pipeline — issues show `hasFile` without any download — and per-group success/blocked outcomes render (blocked reasons visible, consistent with the manual-import overlay's reasons presentation)

#### Scenario: Unconfigured and empty states are explicit

- **WHEN** no root folders are configured, or a scan finds nothing to import (fully-mapped library)
- **THEN** the screen says so explicitly (pointing at Settings for the former) — never a blank or misleading empty results area

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
- **Notes**: Thin screen over the new blocklist read/delete API; blocklist WRITE behavior stays DL/SRCH area. Lives in the Activity nav group.

#### Scenario: Banned release visible with reason, removable

- **WHEN** a failed download's release is on the blocklist
- **THEN** it renders with source title, series/issue link, indexer, date, and the ban reason verbatim; removing it deletes the row so the release becomes grabbable again

#### Scenario: Bulk removal

- **WHEN** the user selects several rows and removes them
- **THEN** all selected rows are deleted and the list refreshes; a mid-batch failure reports which removals did not happen

### Requirement: FRG-UI-018 — Weekly pull / calendar view

The UI SHALL provide a release-calendar or weekly-pull view of upcoming/recent issues for watched series with want/skip actions per entry.

- **Milestone**: M3
- **Source**: mylar-feature-surface.md §1 weekly pull + §PULL capability map; sonarr-architecture.md §7.1 Calendar (+iCal).
- **Notes**: Backend is PULL area (not in this baseline) — this UI requirement is deliberately B and blocked on PULL; recorded here so the screen inventory is complete. Choose Mylar pull-list shape vs Sonarr calendar shape at PULL design time.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A watched series with an issue shipping this week shows it in the view; marking it wanted feeds the search pipeline.

