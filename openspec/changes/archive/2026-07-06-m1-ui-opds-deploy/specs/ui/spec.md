## MODIFIED Requirements

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

The UI SHALL provide a series detail screen showing series metadata (poster, publisher, year, status, overview), the full issue list with per-issue monitored toggle, file presence/format, and per-issue actions (automatic search, interactive search), plus series-level actions (refresh, rescan, edit, delete with optional folder removal) dispatched via the command endpoint.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.4 (Series details), §7.2 command endpoint; mylar-feature-surface.md §SER (per-series overrides, forceRescan).
- **Notes**: NO reading/preview affordance on issue rows — reader is permanently out of scope; the consumption path is OPDS. Per-series overrides (alternate search names, etc.) are M2 fields on this screen.

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

### Requirement: FRG-UI-005 — Add-series search screen

The UI SHALL provide an add-series screen where the user searches ComicVine by title (or pastes a ComicVine volume id/URL), sees candidate volumes with poster, year, publisher, and issue count, and adds one with root folder, monitoring strategy, and format-profile selections.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.4 (AddSeries lookup), §1.2 add flow; mylar-feature-surface.md §SER (add by CV search or CV ID).
- **Notes**: First leg of the vertical slice. "Import existing library" mass-add flow is a separate M2 requirement below — keep them distinct.

#### Scenario: Search renders CV candidates with plausibility annotations

- **WHEN** the user types a title and the ComicVine lookup returns candidates
- **THEN** each candidate renders poster, year, publisher, and issue count, and any plausibility annotations returned are rendered on the candidate

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
