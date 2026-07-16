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

### Requirement: FRG-UI-002 — Design token layer with the foragerr dark theme

The frontend SHALL centralize all colors, typography, spacing, radii, and
shadows in a design-token layer (CSS variables) consumed by every component —
no hardcoded values in components. The token set SHALL implement the owner's
design: dark warm-neutral surfaces (app background `#202020`, panels/sidebar/
header `#262626`, card `#282828`, raised/menu `#2b2b2b`, input `#1c1c1c`),
one green accent family (`#57b877` primary, `#7fce9a` light/active, tint
backgrounds at 14–16% alpha, dark knockout text on accent), semantic status
hues (owned/complete green, missing/importing amber `#e5a54b`, downloading
blue `#5d9cec`, queued grey), progress-track colors (complete `#2f5d40`,
incomplete `#4a2523`, fill `#57b877`), publisher tint and accent palettes as
data maps, and format-chip colors (TPB blue, Deluxe amber, Omnibus green).
Typography SHALL be Roboto (300/400/500/700, self-hosted) with the design's
scale (page titles 30–33px/700 down to uppercase section labels 10–11px with
letter-spacing), monospace for format labels; icons SHALL be Font Awesome 6
Free, self-hosted. No external font/icon CDN requests SHALL occur at runtime.

#### Scenario: Components consume tokens only

- **WHEN** the frontend source is inspected
- **THEN** colors, font sizes, radii, and shadows in components reference the
  token layer (CSS variables or the exported token/palette maps), and the
  token file is the single place the palette above appears

#### Scenario: No external asset fetches

- **WHEN** the built SPA loads in a browser with the network restricted to
  the application origin
- **THEN** fonts and icons render correctly from self-hosted assets and no
  request leaves the origin

### Requirement: FRG-UI-003 — Library index screen

The UI SHALL provide a library index screen listing all series in three view
modes: **Posters** — a responsive `auto-fill` grid with selectable poster
sizes (S/M/L ≈ 134/162/196px), each card a 2:3 cover with a monitored
bookmark chip, a publisher chip, the book-type badge where typed
(FRG-UI-022), an owned/total progress strip (track color reflecting complete
vs incomplete, accent fill), and title + status/year subline (an `N vols`
chip appears on the grouped stacked card only — FRG-UI-021); **Overview** —
horizontal rows with cover thumb, title, status pill, publisher/meta, a wide
progress bar and percent complete; **Table** — a dense table with monitor
icon, Title (+ book-type badge), Publisher, Issues (mini progress), Status,
and Year columns. Above the content a count line SHALL read
`N comics · N monitored · N with missing issues` with the monitored and
missing counts in their semantic colors. The toolbar SHALL carry the view
switcher and three dropdown menus in the design's raised-menu style —
**Options** (poster-size segmented control, group-volumes toggle), **Sort**
(Title, Publisher, Issues owned, Year; check mark on the active choice;
sorting applies to the flat views, so the menu is disabled while grouping is
on), and **Filter** (All, Monitored, Missing issues, Continuing; each option
showing its count; plus an EDITIONS section carrying the FRG-UI-022
collected-editions filter with counts) — plus a text filter; a click in the
content region SHALL close any open menu without activating the content
beneath it. View mode, poster size, sort, and filter selections SHALL
persist across sessions.

- **Milestone**: M1 (redesigned to the owner's design in M4, m4-library-views)
- **Source**: sonarr-architecture.md §7.4 (Series index); mylar-feature-surface.md UI section; owner design handoff (library screen, options/sort/filter menus), reviewed 2026-07-10.
- **Notes**: "UI browse" leg of the vertical slice. The M4 redesign supersedes the M1 visual language; behavior (local covers only, detail navigation, filtering semantics) is unchanged. Publisher tints/accents come from the ch1 palette maps.

#### Scenario: Poster grid renders from local cover endpoint

- **WHEN** the index renders a mocked library of 50+ series in poster mode
- **THEN** each card shows the title, monitored bookmark, publisher chip, and owned/total progress strip, and every poster `img` `src` points at the local cover endpoint (no external ComicVine image host)

#### Scenario: View-mode switcher covers all three modes

- **WHEN** the user cycles the view switcher through Posters, Overview, and Table
- **THEN** the same series render as poster cards, overview rows, and dense table rows respectively, and returning to a mode restores its layout

#### Scenario: Poster size control

- **WHEN** the user selects S, M, or L in the Options menu
- **THEN** the poster grid re-lays out at the corresponding card size and the choice persists across a reload

#### Scenario: Sort and filter menus drive the list

- **WHEN** the user picks a Sort option and a Filter option, and types a substring into the text filter
- **THEN** the rendered order matches the sort, only series meeting the filter (and substring) remain, the active sort shows its check mark, and each filter option displays its live count

#### Scenario: Count line reflects the library

- **WHEN** the index renders
- **THEN** the count line shows total, monitored (accent), and with-missing-issues (warn) counts consistent with the rendered library

#### Scenario: Menus close on content interaction

- **WHEN** a toolbar menu is open and the user clicks in the content region
- **THEN** the menu closes without activating content beneath it unexpectedly

#### Scenario: Selecting a series opens detail

- **WHEN** the user clicks a series card, overview row, or table row
- **THEN** the series-detail screen opens for that series

### Requirement: FRG-UI-004 — Series detail screen

The UI SHALL provide a series detail screen rendered to the M4 design: a
hero whose backdrop is the series cover blurred and darkened (gradient into
the page background) behind the sharp 2:3 cover (~206×309) and metadata —
title, book-type/volume badge where applicable, a meta row (monitored
state, publisher, first-issue date, status, issue count, file formats), an
icon-over-label action row (Search Monitored, Search All, Refresh, Edit,
Delete with optional file removal, plus a ⋯ overflow carrying the
remaining series commands — Rescan and Rename Files — so no M1 action
loses reachability; Search All runs the series search over all missing
issues regardless of monitored state), and the overview paragraph, which SHALL collapse behind a
"show more" toggle when it overflows its clamp. Below the hero a bordered
panel SHALL carry an `Issues · N / Collections · N` segmented toggle and a
compact owned/total progress bar; the Issues tab is a dense table —
selection checkbox (FRG-UI-025), per-issue monitored toggle, verbatim
issue number, release date, status pill (file present = success, missing =
warn, unreleased = neutral), collected-in chips (FRG-SER-020 memberships,
book-type-toned), file size, and per-row automatic + interactive search
actions. Covers come exclusively from the local cover endpoint, including
the backdrop. The screen SHALL additionally surface the series' credited
creators (from the stored credits, FRG-CRTR-002) as a compact creators
strip — each entry showing the creator's name and normalized roles and
navigating to the creator profile (FRG-UI-028) or to the creators grid
focused on this series (FRG-UI-027); the strip is absent when the series
has no ingested credits.

- **Milestone**: M1 (redesigned to the owner's design in M4,
  m4-series-detail; creators strip added in M5, m5-creators-screens)
- **Source**: sonarr-architecture.md §7.4 (Series details), §7.2 command
  endpoint; owner design handoff §2, reviewed 2026-07-10; handoff §8
  (credits open creator pages).
- **Notes**: The M4 redesign supersedes the M1 visual language; command
  dispatch, per-issue monitor semantics, verbatim issue numbers
  (never coerced), and the e2e selector contract (`issue-row-<issueId>`,
  per-row search accessible names, `interactive-search-overlay`,
  `command-status`) are unchanged. m5-creators-screens delivers the
  creators strip this requirement previously deferred ("Creator credits
  await M5").

#### Scenario: Hero renders from local covers with actions

- **WHEN** the detail screen renders for a series with a cached cover
- **THEN** both the blurred backdrop and the sharp cover use the local cover endpoint, the meta row shows monitored/publisher/first-issue/status/count, and each action button dispatches its existing command

#### Scenario: Long overview collapses behind show-more

- **WHEN** a series' overview text overflows the clamp
- **THEN** it renders collapsed with a "show more" control that expands it (and collapses again), while a short overview shows no control

#### Scenario: Issues table anatomy

- **WHEN** the Issues tab renders a series with owned, missing, and unreleased issues
- **THEN** each row shows checkbox, monitor toggle, verbatim issue number, release date, the correct status pill, any collected-in chips, size for file-backed rows, and working per-row search actions

#### Scenario: Existing command and search flows survive the redesign

- **WHEN** the operator toggles an issue's monitored flag, runs an automatic search, and opens interactive search from a row
- **THEN** each behaves exactly as before the redesign (same endpoints, same command-status surface, same overlay)

#### Scenario: Creators strip surfaces stored credits

- **WHEN** the detail screen renders a series with ingested credits, and
  separately one with none
- **THEN** the credited series shows the creators strip (names + roles)
  whose entries navigate into the creator surfaces, and the creditless
  series renders no strip and no placeholder

### Requirement: FRG-UI-005 — Add-series search screen

The UI SHALL provide an add-series screen where the user searches ComicVine by title (or pastes a ComicVine volume id/URL), sees candidate volumes as expandable result cards per the M4 design handoff — cover, name, year, publisher, issue count, a short description/deck, and an "In library" badge when already present — in the relevance order the API returns (FRG-META-015), and adds one through an inline add-config panel with root folder, format-profile, monitoring-strategy, search-on-add, and collect-as (single issues / collected editions) controls. As the user types a title, the screen SHALL offer a debounced ComicVine autosuggest dropdown backed by the bounded suggest endpoint (FRG-API-017): it fires only when the trimmed term is at least three characters, is debounced, and is cancellable so that a response for a superseded term is discarded and never rendered; selecting a suggestion behaves exactly like selecting a full-lookup candidate (it opens the same add panel). The autosuggest is an accelerator over — and never replaces — the full-lookup submit path: the screen SHALL still distinguish the non-success search outcomes — a lookup error (including ComicVine credential failure, classified by the API's machine-readable field discriminator and rendered with guidance to check Settings), an incomplete result (degraded walk), a capped result (advising a narrower search), and a genuinely empty result — never rendering an error, degraded, or capped outcome as plain "no results", rendering exactly one outcome state at a time, and always honouring a re-submitted search (a same-term retry issues a fresh lookup rather than serving the failed or degraded result from cache). A ComicVine credential failure from the autosuggest SHALL drive the same actionable "check the ComicVine key in Settings" state as the full lookup, via the same field discriminator.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §7.4 (AddSeries lookup + as-you-type suggestion), §1.2 add flow; mylar-feature-surface.md §SER (add by CV search or CV ID); m2-search-autosuggest (debounced suggest accelerator); design handoff §3 add-new (m4-add-new).
- **Notes**: First leg of the vertical slice. "Import existing library" mass-add flow is a separate M2 requirement — keep them distinct. Outcome-state distinction added in m2-lookup-error-surfacing: a missing/invalid ComicVine key previously rendered as "no results". m2-search-autosuggest: the autosuggest is a passive accelerator riding FRG-API-017 (first-page-only) — the full-lookup submit path with its incomplete/truncated/empty outcome states is unchanged and remains the authoritative search; the header quick-search (FRG-UI-019) can seed this screen's input via a prefilled term. m4-add-new: visuals rebuilt to the design handoff (expandable cards, inline panel, monitor as a segmented control); plausibility chips give way to the ranked order plus the "In library" badge, with the signals still available on the candidate payload. The collect-as control is untouched by default (title-cue derivation applies, FRG-SER-018); an explicit choice maps to the locked add-time book-type (collected editions → `tpb`, refinable to gn/hc later on the series).

#### Scenario: Debounced autosuggest fires only past the character threshold

- **WHEN** the user types a title into the add-series search input
- **THEN** no autosuggest request is issued until the trimmed term is at least three characters, the request is debounced (not one per keystroke), and the dropdown renders bounded ComicVine candidates from the suggest endpoint

#### Scenario: Stale autosuggest responses are discarded

- **WHEN** the user types further characters (superseding an earlier term) while an earlier autosuggest request is still in flight
- **THEN** the earlier request is cancelled or its response discarded, so only the latest term's suggestions can render — a slow stale response never overwrites newer suggestions

#### Scenario: Selecting a suggestion opens the add panel like a full candidate

- **WHEN** the user selects an entry from the autosuggest dropdown
- **THEN** the same add panel opens as when selecting a full-lookup candidate (root folder, format profile, monitor strategy, search-on-add, collect-as), with no divergent add path

#### Scenario: Autosuggest credential failure reuses the actionable error state

- **WHEN** an autosuggest request fails because the ComicVine API key is missing or invalid (the suggest endpoint's 503 with `field="comicvine_api_key"`)
- **THEN** the screen renders the same actionable state that names the ComicVine API key as the likely cause and points at Settings — classified by the field discriminator, not by message prose, and not as an empty "no results" dropdown

#### Scenario: Search renders CV candidates as design-handoff result cards

- **WHEN** the user types a title and the ComicVine lookup returns candidates
- **THEN** each candidate renders as a result card with cover, name, year, publisher, issue count, and description/deck, an "In library" badge when the series is already present, in the API's relevance order (FRG-META-015) without client-side reordering

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
- **THEN** the inline add-config panel renders controls for root folder, format profile, monitor strategy (segmented), search-on-add, and collect-as (single issues / collected editions)

#### Scenario: Collect-as left untouched preserves derivation

- **WHEN** the user adds a series without touching the collect-as control
- **THEN** the add request carries no explicit book-type and the series is typed by title-cue derivation exactly as before (FRG-SER-018); an explicit choice sends the corresponding locked book-type

#### Scenario: Adding navigates to detail with refresh command visible

- **WHEN** the user confirms the add
- **THEN** the app navigates to the new series' detail route and a refresh command is visible as in-progress on that screen

#### Scenario: A prefilled term seeds the search on mount

- **WHEN** the Add Series screen is opened with a term prefilled (e.g. from the header quick-search fall-through)
- **THEN** the search input is seeded with that term and the debounced autosuggest runs for it on mount, so the local-miss → remote-add handoff lands the user in a live search

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

The UI SHALL provide a System area with three screens: a Status screen (application version and build info, managed paths, and runtime info), a Health screen (current health warnings with remediation hints plus the per-component health table with each component's state — ok / degraded with its disabled-until countdown / error), and a Tasks screen (the scheduled-task table with last/next run and per-task force-run buttons, including a prominent "Back up now" action on the backup task). Force-running a task SHALL reflect the returned command's status until it reaches a terminal state.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §7.4 (System/{Status, Tasks}), §7.1 Health; mylar-feature-surface.md §SCHED (force-run from UI, jobhistory).
- **Notes**: Lives in a dedicated System nav group (Sonarr shape). Reads are poll-first via React Query (health clears on the next poll when a component recovers — FRG-NFR-011). Status shows only managed `/config` paths and runtime — never secrets (FRG-API-014). The Tasks force-run POSTs to `POST /api/v1/system/task/{name}` (resets the timer, returns the command id to track). The Health screen renders `GET /api/v1/health` warnings (with hints) and the `GET /api/v1/system/health` per-component table. Log-viewer screen stays milestone B — server-side log files suffice for a single admin.

#### Scenario: Status screen shows version, paths, and runtime

- **WHEN** the System → Status screen loads
- **THEN** it renders the application version/build info, the managed paths (config dir, database path, backups dir, root-folder count), and runtime info (uptime, python/OS), and displays no secret values

#### Scenario: Health screen shows warnings with remediation and per-component state

- **WHEN** an indexer is in failure back-off and the System → Health screen loads
- **THEN** the warnings list shows the failing indexer with its remediation hint, the per-component table shows that indexer `degraded` with its disabled-until countdown, and once it recovers a subsequent poll clears the warning without a manual refresh or restart

#### Scenario: Tasks screen force-runs a task and tracks its command

- **WHEN** the user clicks a task's force-run button (or "Back up now" on the backup task) on the System → Tasks screen
- **THEN** `POST /api/v1/system/task/{name}` is issued and the row reflects the returned command status as it progresses to terminal, and the task's last-run/next-run update afterwards

#### Scenario: Healthy system Health screen is explicitly clear

- **WHEN** no component is unhealthy and the Health screen loads
- **THEN** it shows an explicit "all healthy" state (distinct from a loading or error state) and the per-component table shows every component `ok`

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

The UI SHALL provide a Calendar screen at `/calendar` rendering the weekly
release projection (FRG-API-019) as a **date-grouped agenda** per the design
handoff (§4 Calendar) — one week at a time, days as vertical groups, never a
7-column month/week grid. The screen SHALL provide:

- **Week navigation**: previous / "This Week" / next controls plus a
  human-readable range label; each navigation step re-queries the endpoint
  with the target ISO week (the server holds no navigation state). "This
  Week" SHALL return to the current store-date week from any offset.
- **Scope toggle**: a `Following / All releases` segmented control,
  **defaulting to All releases** — the weekly view doubles as discovery of
  unfollowed books (owner decision 2026-07-11; Mylar pull-list philosophy,
  superseding the handoff's Following default). Following shows only
  entries linked to library series (matched or pending-refresh); All
  releases shows every entry.
  In Following scope, a day with hidden entries SHALL show a
  "+N more titles shipping" note; in All releases scope, a day with followed
  entries SHALL show an "N followed" count.
- **Publisher filter**: a select over the publishers present in the loaded
  week (plus "All publishers"), filtering the agenda client-side.
- **Info banner**: a one-line explanation of the weekly-drop reality with
  the week's followed/total counts, varying by scope.
- **Day groups**: date numeral + weekday + month in the gutter, an accent
  bar, and release cards (publisher-tinted cover spine with publisher accent
  edge, series title, issue number · publisher, state icon). Wednesday SHALL
  carry a "New Comic Day" badge; the current date SHALL carry a "Today"
  badge. Days with no visible entries are omitted.
- **Derived-state display**: each linked card's state icon/tone SHALL be a
  projection of the entry's `state` (missing/wanted, downloading,
  downloaded, unmonitored, pending-refresh) — never a status stored on the
  pull entry (D4). Not-yet-released entries (store date in the future) are
  visually marked as such.
- **Empty state**: a friendly empty message when the filtered week has no
  entries, distinct from the error state.

The Calendar nav entry SHALL enter the sidebar in this change (shipped-screens
rule, FRG-UI-023). The screen SHALL remain functional when the pull source is
unconfigured or degraded, rendering the metadata-derived half of the
projection (FRG-PULL-001 passthrough). Per-entry actions and the new-series
strip are governed by FRG-PULL-007 and FRG-PULL-008.

- **Milestone**: M4
- **Source**: design handoff v2 §4 (calendar.png + dc.html calendar region);
  mylar-feature-surface.md §1 weekly pull; sonarr-architecture.md §7.1
  Calendar; FRG-API-019 (the read surface).
- **Notes**: Shape decision resolved: date-grouped agenda (design handoff),
  not Mylar pull-list table nor Sonarr month grid — comics ship in one
  Wednesday drop, a grid piles everything on one column. Scope/publisher
  filtering is client-side over the fetched week (the endpoint pages at up
  to 200 rows; the client aggregates pages when a week exceeds one page).
  No iCal feed (non-goal).

#### Scenario: Default load shows the current week's ALL releases

- **WHEN** the Calendar screen loads with no navigation state
- **THEN** it requests the current store-date week (no `week` param needed)
  and renders every entry — followed and unfollowed alike — grouped by day
  with the range label, marking Wednesday "New Comic Day" and the current
  date "Today", so the week reads as a discovery surface first

#### Scenario: Week navigation is parameterised and reversible

- **WHEN** the user clicks next, then next, then "This Week"
- **THEN** each click re-queries the endpoint with the correct target ISO
  week (+1, +2, then current), the range label follows, and no server-side
  navigation state is involved

#### Scenario: Following scope narrows to library entries

- **WHEN** the user switches the scope toggle to "Following" on a week
  containing both linked and unmatched entries
- **THEN** only entries linked to library series remain, days show the
  "+N more titles shipping" note for what was hidden, and switching back to
  All releases restores the full week with its "N followed" day counts

#### Scenario: Derived state is projected, never stored

- **WHEN** a linked entry's card renders and the underlying issue's
  monitored flag or queue presence changes
- **THEN** the card's state icon reflects the new derived state after the
  relevant query invalidation, and no pull-entry field was written to effect
  the change

#### Scenario: Degraded pull source still renders the local projection

- **WHEN** the pull source is unconfigured or its last fetch failed
- **THEN** the Calendar still renders watched-series issues store-dated in
  the viewed week with correct derived state, and no error state replaces
  the agenda

### Requirement: FRG-UI-019 — Global header quick-search over the local library

The UI SHALL provide a search box in the application header that fuzzy-matches the user's query against the LOCAL library's series titles AND aliases using data already cached on the client (the `['series']` index query), issuing NO network request per keystroke. The results list SHALL be keyboard-navigable (arrow keys move the active result, Enter selects it, Escape closes the list); selecting a matched series SHALL navigate to that series' detail page. The results SHALL always include, as the final row, a "Search ComicVine for '<term>'…" fall-through that navigates to the Add Series screen with the term prefilled — present even when local matches exist, so the remote-add escape hatch is never hidden.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §7.4 (global "go to series" affordance); mylar-feature-surface.md §SER (search-then-add bridge); FRG-UI-001 (client state via React Query — the cached `['series']` index is the match source), FRG-UI-005 (the Add Series screen the fall-through routes into).
- **Notes**: Purely client-side matching over already-delivered data (the series index resource already carries `aliases`), so there is no per-keystroke server load and no new API. Ranking is exact/prefix > word-boundary > subsequence, casefolded. When the `['series']` cache is empty or still loading, the box degrades to only the fall-through row rather than erroring. The fall-through carries the term into Add Series via navigation state, which seeds that screen's input and its debounced autosuggest (FRG-UI-005). No new SOUP is expected for the matcher; a library choice would trigger a SOUP-register delta.

#### Scenario: Local titles and aliases match without a network call

- **WHEN** the user types into the header search box and a series whose title OR one of whose aliases fuzzy-matches the term exists in the cached library index
- **THEN** that series appears in the results list ranked by match quality, and no network request is issued for the keystrokes (matching runs entirely over the client-cached `['series']` data)

#### Scenario: Keyboard navigation and selection

- **WHEN** results are shown and the user presses the down/up arrows and then Enter
- **THEN** the active result moves with the arrows, Enter navigates to the active series' detail page, and Escape closes the results list without navigating

#### Scenario: Fall-through to ComicVine add is always present

- **WHEN** the results list renders, whether or not any local series matched
- **THEN** its final row is "Search ComicVine for '<term>'…", and activating it navigates to the Add Series screen with the typed term prefilled (seeding that screen's search input), bridging a local miss to a remote add

#### Scenario: Empty or loading cache degrades gracefully

- **WHEN** the `['series']` index is empty or still loading and the user types a term
- **THEN** the box shows only the "Search ComicVine for '<term>'…" fall-through row (no error, no spinner masquerading as results), so the add bridge still works before the library index has loaded

### Requirement: FRG-UI-020 — Settings: General with ComicVine metadata credential

The UI SHALL provide a **Settings → General** section (a nav item and route, using the bespoke single-form config-singleton pattern, not the provider list+modal machinery) that lets the user set the ComicVine API key via a **masked, write-only** field and verify it with a **Test** connectivity button that mirrors the indexer test-button pattern. The field SHALL never display the stored key: when a key is configured it shows a "currently set" indicator (placeholder dots) and a blank save keeps the stored value. When the key's source is the environment (`FORAGERR_COMICVINE_API_KEY`, as reported by the settings resource), the field SHALL render in a **read-only, environment-managed** state with guidance to edit the environment variable, instead of a silently-ineffective editor. The Test button SHALL report connectivity success or failure without revealing the key. The ComicVine credential-failure guidance shown on the Add Series (and existing-library import) screens SHALL link into this section, so "check Settings" routes to a real place to fix the key.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §4 (Settings → General; provider test buttons); mylar-feature-surface.md §7 (config surface); m2-first-run-defaults (the ComicVine key gets a UI home and the AddSeries error a real destination); FRG-API-018 (the resource this screen reads/writes/tests), FRG-UI-008/FRG-IDX-003 (the schema-driven form + connectivity-test pattern reused), FRG-UI-009 (the masked write-only secret-field pattern), FRG-UI-005 (the Add Series screen whose credential error links here).
- **Notes**: Placement is General (not Metadata): the Sonarr-shaped home for app-wide config singletons and future global settings; Metadata was considered and rejected as narrower. The screen follows the MediaManagement save-bar pattern with the SchemaForm password widget for the key (write-only — never echoes the stored value, `••••••••` when set, omits a blank field on save) and a Test mutation on the `useTestProvider` pattern hitting the connectivity endpoint. The env-read-only state is driven purely by the resource's reported `source`, so the operator never types into a field the environment shadows. The Add Series / Library Import prose gains a router `<Link>` exactly like the existing no-root-folders link; the credential classification stays on the machine-readable `field="comicvine_api_key"` discriminator, not message prose.

#### Scenario: The ComicVine key field is masked and write-only

- **WHEN** the Settings → General section renders with a ComicVine key already configured
- **THEN** the key field shows a "currently set" masked indicator and never renders the stored key value into the DOM, and saving the form with the field left blank keeps the stored key rather than clearing it

#### Scenario: Saving a key persists it and the Test button confirms connectivity

- **WHEN** the user enters a ComicVine API key and saves, then presses Test
- **THEN** the key is submitted to the settings resource (persisted and applied live), and the Test button reports connectivity success or failure without displaying the key

#### Scenario: An environment-supplied key renders read-only with guidance

- **WHEN** the settings resource reports the ComicVine key source as `environment`
- **THEN** the key field renders in a read-only, environment-managed state with guidance to change the `FORAGERR_COMICVINE_API_KEY` environment variable, rather than an editable field whose save the environment would shadow

#### Scenario: The Add Series credential error links to this section

- **WHEN** an Add Series (or existing-library import) ComicVine lookup fails on a missing/invalid key and the actionable credential-error state renders
- **THEN** its "check Settings" guidance is a link that navigates to the Settings → General ComicVine credential section, classified by the `field="comicvine_api_key"` discriminator rather than message prose

### Requirement: FRG-UI-021 — Grouped library view

The Comics (library index) screen SHALL offer a **grouped** display mode alongside the
poster/overview/table modes: in poster mode, a franchise's volumes SHALL stack into a
single card with a layered offset-shadow treatment and an `N vols` chip, the progress
strip showing summed owned/total across members; in row/table contexts franchise
groups render as headers carrying the group title and an aggregated stat roll-up,
with their member runs nested beneath and collapsible. A franchise with a single run
SHALL render as an ordinary card/row (no group chrome). The mode SHALL be the
group-volumes toggle in the Options menu; switching it SHALL not change series
identity, monitoring, or any per-series action, and the flat views SHALL remain
available and unchanged. From the grouped view the operator SHALL be able to reach
the group rename / series-reassign affordance (FRG-SER-017).

#### Scenario: Grouped posters stack into one card

- **WHEN** the operator enables group-volumes in poster mode with a multi-volume franchise present
- **THEN** the franchise renders as one stacked card with the layered shadow, an `N vols` chip, and summed owned/total on the progress strip, while single-run franchises render as ordinary cards

#### Scenario: Grouped mode nests runs under franchise headers

- **WHEN** the operator switches to grouped mode in a row/table context with multiple runs of one title
- **THEN** the runs appear nested under one collapsible franchise header with a roll-up stat, and single-run franchises render as ordinary rows

#### Scenario: Grouping is display-only

- **WHEN** the grouped view is shown
- **THEN** per-series monitored state, actions, and navigation behave exactly as in the flat views, and toggling back to a flat view shows the same series unchanged

#### Scenario: Correcting a group from the view

- **WHEN** the operator renames a group or reassigns a run from the grouped view
- **THEN** the change takes effect through the existing FRG-SER-017 affordance exactly as before the redesign

### Requirement: FRG-UI-022 — Collected-edition (trade) surfacing

The library and series-detail UI SHALL surface a series' collected-edition type
(FRG-SER-018): a **book-type badge** (TPB / GN / HC) on the series card in the library
grid — including within a franchise group (FRG-UI-021) — and on the series-detail hero,
so a collected edition is visually distinct from a single-issues run. The library SHALL
offer a **filter** to show only collected editions or only single-issues runs. The
surfacing SHALL be display-only: every per-series action, navigation, monitored state,
and the wanted machinery SHALL behave exactly as for an untyped series, and a series
with a null book-type SHALL show no badge.

#### Scenario: Collected-edition badge appears

- **WHEN** a series typed `tpb`/`gn`/`hc` is shown in the library grid or its detail page
- **THEN** a corresponding book-type badge is displayed, while a null-typed single-issues run shows no badge, and all per-series actions are unchanged

#### Scenario: Collected-editions filter

- **WHEN** the operator applies the collected-editions filter in the library
- **THEN** only collected-edition (or only single-issues) series are shown, without changing any series' identity, monitoring, or wanted state

### Requirement: FRG-UI-023 — Application shell

The SPA SHALL render every screen inside a fixed three-part shell: a 212px
sidebar (logo lockup in a 60px header row; a nav list where each item has
icon and label, and where a count badge is shown it is reserved for
active/in-progress work only — Activity = queue length is the sole count
badge; the Comics and Wanted nav items carry NO count badge (the library size
is shown on the Comics page; missing counts live on the Wanted page, in issue
units — a nav badge counting series-with-missing misreads against a page
listing missing issues); a SYSTEM section with Settings and System; a footer
status row showing a health indicator and the running version), a 60px global
header (the existing library quick-search input, health and system icon
buttons), and a per-screen toolbar slot above a content region that is the
only scrolling area (no page-level scroll). The active nav item SHALL carry
the accent treatment (inset accent bar, accent icon). The nav SHALL list only
screens that exist — entries for future screens (Calendar, Creators) appear in
the change that ships the screen. Pending/missing/library-size counts SHALL NOT
be badged on the nav; only active-work counts (the queue) SHALL be.

#### Scenario: Shell frames every route

- **WHEN** any existing route (library, series detail, wanted, activity,
  settings, system) is visited
- **THEN** the sidebar, global header, and toolbar slot render with the
  content region scrolling independently, and the active nav item carries
  the accent treatment

#### Scenario: The queue badge is live

- **WHEN** the queue gains or loses an item while the app is open
- **THEN** the Activity/Queue nav badge updates without a page reload (React
  Query + WS invalidation)

#### Scenario: Comics and Wanted nav items carry no count badge

- **WHEN** the sidebar is inspected while the library has series and some of
  them have missing issues
- **THEN** the Comics and Wanted nav items show icon and label with no count
  badge; the library size appears on the Comics page and the missing count on
  the Wanted page, in issue units

#### Scenario: Only shipped screens appear in the nav

- **WHEN** the sidebar nav is inspected
- **THEN** every entry routes to an implemented screen, and no entry exists
  for screens not yet shipped

### Requirement: FRG-UI-024 — System → Logs screen

The SPA SHALL provide a Logs screen under the sidebar's SYSTEM group
(`/system/logs`) rendering the FRG-API-021 resource as a dense table —
time, level pill (semantic colors: ERROR danger, WARNING warn, INFO
neutral, DEBUG muted), logger, message — with a minimum-level filter, a
logger-prefix filter, and a **Follow** toggle. With Follow on, the screen
SHALL poll the resource on a short interval (≥ 2s) and keep the newest
records in view; with Follow off, polling SHALL stop and the operator can
page back through the buffer. Polling SHALL also stop when the screen
unmounts. The screen SHALL render an honest empty state when the buffer is
empty and an error state when the resource fails (never a silent blank
per the UAT negative-path rule).

- **Milestone**: M4 (m4-logs-viewer)
- **Source**: owner request 2026-07-10; Sonarr System→Log prior art.
- **Notes**: Nav entry ships with this screen (FRG-UI-023 shipped-screens
  rule). No WS log family — polling only (design decision 2).

#### Scenario: Logs table renders with filters

- **WHEN** the operator opens System → Logs with mixed-level records buffered and applies a minimum level and a logger prefix
- **THEN** the table shows only matching records (time, level pill, logger, message), newest first

#### Scenario: Follow polls and stops

- **WHEN** Follow is on
- **THEN** the resource is re-fetched on the polling interval and new records appear without a reload; turning Follow off (or leaving the screen) stops the polling

#### Scenario: Empty and error states are honest

- **WHEN** the buffer is empty, or the log resource request fails
- **THEN** the screen states that no records are buffered (or that loading failed) rather than rendering a silent blank table

### Requirement: FRG-UI-025 — Issue bulk selection and actions

The Issues tab SHALL support multi-issue selection: per-row checkboxes, a
header select-all/deselect-all, and **shift-click range selection** (the
span between the last plainly-clicked row and the shift-clicked row). While
a selection is active a **labeled action bar** SHALL appear showing the
selection count and explicit actions — Monitor selected, Unmonitor
selected, Search selected — and SHALL disappear when the selection clears.
Bulk monitor/unmonitor SHALL use the existing bulk mutation; Search
selected SHALL dispatch the existing per-issue automatic-search command
sequentially through the command queue. Selection state is view-local
(cleared on leaving the screen).

- **Milestone**: M4 (m4-series-detail)
- **Source**: owner demo feedback 2026-07-10 ("no way to make them
  monitored… not sure what the checkboxes do"; shift-range + select all).
- **Notes**: Replaces the unlabeled header bookmark button.

#### Scenario: Shift-click selects a range

- **WHEN** the operator clicks one row's checkbox then shift-clicks another several rows away
- **THEN** every row in the span is selected, and the action bar shows the selection count

#### Scenario: Labeled bulk actions apply to the selection

- **WHEN** rows are selected and the operator uses Monitor/Unmonitor/Search selected
- **THEN** exactly the selected issues are affected (monitored flags via the bulk mutation; one search command per selected issue, sequentially), and clearing the selection hides the bar

#### Scenario: Select all and deselect all

- **WHEN** the operator uses the header checkbox
- **THEN** all visible issue rows toggle selected/deselected together

### Requirement: FRG-UI-026 — Collections tab

The detail panel's Collections tab SHALL list the series' declared
collected books (FRG-API-022): each with a book-type-toned format chip,
the collected book's title, its "Collects …" range labels, release date,
and the singles-coverage status rendered as a pill (`collected` success,
`partial` warn, `none` neutral). Each entry SHALL offer **Open**
(navigate to the trade series' detail) and an **edit-containment**
affordance opening a dialog where the operator declares ranges: a target
series picker (library series only), start/end issue pickers from that
series, support for multiple sub-ranges, and delete. The tab count in the
segmented toggle SHALL reflect the number of collected books. An empty
state SHALL explain that collections appear when containment is declared.

- **Milestone**: M4 (m4-series-detail)
- **Source**: owner design handoff §2 (Collections tab); FRG-SER-020/API-022.
- **Notes**: Display + declaration only — no acquisition action here
  (FRG-SER-019). Remote trade discovery belongs to the add flow.

#### Scenario: Collections list with coverage pills

- **WHEN** the Collections tab renders for a series with a fully-covered and a partially-covered declared range
- **THEN** both collected books render with format chip, range labels, release date, and `collected`/`partial` pills respectively, and the toggle shows the right count

#### Scenario: Declaring containment from the dialog

- **WHEN** the operator opens the containment dialog, picks a target series and endpoint issues, adds a second sub-range, and saves
- **THEN** the declaration round-trips through FRG-API-022, the Collections tab and the Issues tab's collected-in chips reflect it, and no monitored/wanted state changed

#### Scenario: Honest empty state

- **WHEN** a series has no declared containment
- **THEN** the Collections tab shows an explanatory empty state (never a silent blank), with the toggle count reading 0

### Requirement: FRG-UI-027 — Creators grid screen

The UI SHALL provide a Creators screen at `/creators` rendered to the design
handoff (§7): a responsive card grid where each card carries a circular
green-gradient initials avatar, the creator's name, a `roles · N series`
line, a Follow/Following pill (green when following) that toggles via the
canonical follow endpoint (FRG-API-023), and a row of small cover spines
for the creator's library works (clicking a spine navigates to that series'
detail). The screen header SHALL show the aggregate count line
(`N creators · M followed`) and a followed-only filter. When navigated to
with a series focus (from a series-detail credit), the screen SHALL show a
dismissible focus chip and list only that series' creators until cleared.
The Creators nav entry SHALL enter the sidebar in this change
(shipped-screens rule, FRG-UI-023). The grid SHALL render an empty state
when no credits exist yet (e.g. backfill still running) that says credits
are still being gathered rather than implying the feature is broken.

- **Milestone**: M5
- **Source**: design handoff §7 (creators.png + dc.html creators region);
  FRG-API-023 (the read surface); owner decision 2026-07-11 (follows
  explicit-only — the pill is the ONLY follow entry point besides the
  profile button).
- **Notes**: Cards show library-derived data only; no ComicVine call.
  Initials avatars per the design — no person images. Follow toggle
  optimistic-updates the card and invalidates the creators queries.

#### Scenario: Grid renders cards to the design from the API

- **WHEN** the Creators screen loads for a library with ingested credits
- **THEN** each card shows the initials avatar, name, roles · series
  count, Follow/Following pill, and its library work spines, and the
  header shows `N creators · M followed` matching the API aggregates

#### Scenario: Follow pill toggles explicitly and only via the endpoint

- **WHEN** the user clicks an unfollowed creator's pill
- **THEN** exactly one `PUT /api/v1/creators/{id}/follow` request is made
  with `{followed: true}`, the pill flips to Following, and no other write
  occurs

#### Scenario: Followed filter and focus chip

- **WHEN** the user enables the followed-only filter, and separately
  arrives with a series focus from series detail
- **THEN** the grid shows only followed creators (filter), respectively
  only that series' creators with a dismissible chip naming the series
  (focus), and clearing either restores the full grid

#### Scenario: Empty state during backfill

- **WHEN** the screen loads while no credits are ingested yet
- **THEN** it renders the credits-still-gathering empty state, not an
  error and not a bare zero-count grid

### Requirement: FRG-UI-028 — Creator profile screen

The UI SHALL provide a creator profile at `/creators/{id}` rendered to the
design handoff (§8): a gradient header carrying the large initials avatar,
the creator's name, roles line, publishers line, and a Follow/Following
button; three stat columns (Series · Issues in library as owned-of-total ·
Publishers) from the profile aggregates (FRG-API-023); and an "In your
library" section of work cards — cover (local endpoint), series title,
volume label where applicable, this creator's role chips for that series,
a meta line, and an owned/total progress bar — each card navigating to the
series detail. The profile SHALL additionally render the
**"More from <name>"** section (handoff §8): the creator's cached external
bibliography (FRG-API-024) as work cards — title, publisher/year meta line,
role chip where known — each carrying an **Add to library** button that
routes into the standard user-driven add flow prefilled for that volume;
the system SHALL never add a series from this section by itself. While the
first fetch is pending the section SHALL show an unobtrusive
gathering state; a creator whose fetched bibliography is empty (or entirely
in-library) SHALL render no section rather than an empty shell. An unknown
creator id SHALL render the standard not-found state.

- **Milestone**: M5
- **Source**: design handoff §8 (creator profile region incl. "More
  from"); FRG-API-023 profile aggregates; FRG-API-024 bibliography
  (m5-creator-suggestions).
- **Notes**: Role chips reuse the normalized-role vocabulary; progress
  bars reuse the house progress styling (series detail's owned/total).
  Back navigation returns to the grid preserving its filter state.

#### Scenario: Profile header and stats match the API

- **WHEN** the profile loads for a creator credited in two library series
- **THEN** the header shows avatar/name/roles/publishers and a working
  Follow button, and the three stat columns equal the API's seriesCount,
  ownedIssues-of-totalIssues, and publisherCount

#### Scenario: Library work cards render and navigate

- **WHEN** the "In your library" section renders
- **THEN** each card shows the local cover, title, this creator's role
  chips, and the whole-series owned/total progress bar, and clicking it
  navigates to that series' detail screen

#### Scenario: Unknown creator is a not-found state

- **WHEN** `/creators/{id}` is opened for an id the API 404s
- **THEN** the screen renders the standard not-found state rather than an
  error boundary or blank page

#### Scenario: More-from cards render from the cache with add hand-offs

- **WHEN** the profile renders for a creator with a fresh cached
  bibliography containing volumes not in the library
- **THEN** the "More from" section lists their cards (title,
  publisher/year), each Add button routes into the standard add flow
  prefilled for that volume, and no series is created without the user
  completing that flow

#### Scenario: Pending and empty bibliography states

- **WHEN** the profile renders while the first bibliography fetch is
  pending, and separately for a creator whose fetched bibliography is
  empty
- **THEN** the pending profile shows the gathering state in place of the
  section, and the empty case renders no section at all

### Requirement: FRG-UI-029 — Sources screen

The web UI SHALL provide a top-level Sources screen per the v2 design handoff: a
Sources nav item that shows an amber `!` when any connected store's session has
expired (a needs-attention state signal) and NO unreviewed-count badge; a store rail
showing the connected/expired/not-connected status of each built store (Humble
Bundle is the only one today — the rail carries no placeholder tab for an unbuilt
integration; a second store tab appears when a second integration ships); a connect
card for
disconnected/expired sources (cookie paste with helper steps, live-validated
Connect, privacy note); and a manage view for connected sources (account bar with
auto-sync toggle, Sync now, Disconnect; count line; All/New/Matched/Ignored filter;
entitlement rows with format chip, status tag, per-status actions, and an expandable
reconcile detail with issue chips per the handoff's edge rules). Session expiry
SHALL surface as the global banner plus amber header/footer health treatments, and
bulk review actions SHALL support the M4 selection pattern including shift-range
select.

#### Scenario: Connect flow

- **WHEN** the operator opens Sources with no connected store, pastes a cookie of plausible length, and clicks Connect
- **THEN** Connect is disabled until the paste threshold, validation feedback comes from the live check (FRG-SRC-002), and success lands on the manage view with entitlements syncing

#### Scenario: Review actions by status

- **WHEN** the operator works the entitlement list
- **THEN** New rows offer Match-to-suggestion / Add / Ignore, Matched rows offer Change / Ignore, Ignored rows are dimmed with Restore, the filter counts stay live, and expanding a row shows the reconcile explanation with issue chips (amber = owned single; suppressed above 12 issues)

#### Scenario: Expiry surfaces globally

- **WHEN** a connected source's session expires while the operator is anywhere in the app
- **THEN** the global banner appears with a Reconnect action, the sidebar footer and header health icon turn amber, the Sources badge shows `!`, and reconnecting (from banner or card) clears all three

#### Scenario: No unreviewed-count badge on the nav

- **WHEN** a connected source has unreviewed `new` entitlements but no expiry
- **THEN** the Sources nav item shows no count badge; the pending-review counts appear only on the Sources page (the manage view's count line and All/New/Matched/Ignored filter), where their comic/non-comic scope is visible

#### Scenario: First sync at scale

- **WHEN** the first sync of a long-standing account lands hundreds of new entitlements
- **THEN** the review list remains responsive, supports bulk select (including shift-range) for accept/ignore, and pending counts are accurate


### Requirement: FRG-UI-030 — Command failure cause surfaced at the watch surface

WHEN a watched command reaches the `failed` status, the web UI SHALL display the command's recorded failure reason alongside the failed status at the surface that watches it (e.g. the series page's command chip), rather than the bare status alone. The reason is the command record's verbatim `error` field (already captured per FRG-SCHED-008); when the record carries no reason, the bare status renders as before.

- **Milestone**: M9 (m9-cv-key-live-reload)
- **Source**: M9 simulated-user finding F1 — a failed first refresh rendered only "Refresh: failed"; the actionable cause (`comicvine authentication failed (HTTP 401)`) was already delivered to the client in the command resource and simply not shown.
- **Notes**: Display-only: `useWatchedCommand` exposes the resource's `error` when terminal-failed; no new API surface. Long reasons may be truncated visually but the full text stays available (e.g. `title`).

#### Scenario: Failed refresh shows its cause

- **WHEN** a series refresh command fails with a recorded error (e.g. a ComicVine authentication failure)
- **THEN** the series page's command status shows the failed status together with the recorded reason, not "failed" alone

#### Scenario: Reason-less failure degrades gracefully

- **WHEN** a watched command fails without a recorded error string
- **THEN** the status chip renders the failed status exactly as before this change

### Requirement: FRG-UI-031 — Ignored publishers editable in Settings

Settings → General SHALL expose the ComicVine ignored-publishers list for viewing and editing (comma-separated, wildcard entries permitted), persisting through the same validated config writer as other file-persisted settings and applying to subsequent searches without restart. When the value is environment-managed (`FORAGERR_COMICVINE_IGNORED_PUBLISHERS` set), the field SHALL render read-only with an environment-managed indication, mirroring the ComicVine key pattern.

- **Milestone**: M9 (m9-publisher-ignore-defaults)
- **Source**: M9 finding F17 recommendation; owner approval 2026-07-16. The setting existed since M1 but was config-file-only.
- **Notes**: The value is not a secret — unlike the key field it echoes its current value for editing. Env-wins precedence is the standard settings rule, surfaced rather than silently ignored.

#### Scenario: Edit and apply without restart

- **WHEN** the operator edits the ignored-publishers list in Settings → General and saves
- **THEN** the value is validated, persisted to `config.yaml`, and the next Add New search applies the updated list with no restart

#### Scenario: Environment-managed value is read-only

- **WHEN** `FORAGERR_COMICVINE_IGNORED_PUBLISHERS` is set in the environment
- **THEN** the Settings field shows the effective value read-only with an environment-managed note, and writes to it are refused

### Requirement: FRG-UI-032 — Hidden-by-ignore-list results are recoverable in Add New

WHEN an Add New search excludes results via the publisher ignore list, the screen SHALL show an explicit count of hidden results with a one-click control that reveals them (flagged as ignore-listed) for that search, together with a path to edit the list in Settings. Nothing is silently dropped; revealing is per-search and does not modify the configured list.

- **Milestone**: M9 (m9-publisher-ignore-defaults)
- **Source**: M9 finding F17; owner approval 2026-07-16 — the recoverable form is what makes a shipped default acceptable (vs Mylar's silent drop).
- **Notes**: Reveal refetches with the include-ignored query mode (FRG-META-007) and badges the ignore-listed candidates; the count line renders only when the count is non-zero.

#### Scenario: Hidden count with one-click reveal

- **WHEN** a search excludes N > 0 results via the ignore list
- **THEN** the results view shows "N result(s) hidden by your publisher ignore list" with a Show control; activating it reveals the hidden candidates, visibly badged, without altering the configured list

#### Scenario: No hidden results, no chrome

- **WHEN** a search excludes nothing
- **THEN** no hidden-results line renders

### Requirement: FRG-UI-033 — Actionable UI-language guidance with settings links

WHEN the web UI shows guidance or an error that names a settings destination (e.g. the ComicVine-key error, the add dialog's root-folder notice), the destination SHALL be rendered as a navigable link to that settings screen, and UI-facing warning/health copy SHALL speak in UI terms (screen names and labels) rather than configuration-key names — config keys stay in logs and admin docs.

- **Milestone**: M9 (m9-ux-diagnosability)
- **Source**: M9 findings F2 and F4 (`docs/research/m9-user-sim-findings.md`).
- **Notes**: Sweep-scoped: the two named surfaces plus the pull-source health remediation (which told a UI user to "verify 'pull_source_url'").

#### Scenario: Credential error links to Settings

- **WHEN** an Add New search fails for a missing/invalid ComicVine key
- **THEN** the guidance names Settings → General as a link that navigates there

#### Scenario: Health remediation speaks UI language

- **WHEN** the weekly pull source is degraded and its health warning renders in the UI
- **THEN** the remediation text names UI surfaces (not raw config-key names)

### Requirement: FRG-UI-034 — Inline root-folder creation in the add dialog

WHEN no root folder is registered and the operator opens the add-series dialog, the dialog SHALL offer registering a root folder inline (path input through the same validated API), and on success SHALL proceed with the add flow without abandoning the dialog or losing the search results.

- **Milestone**: M9 (m9-ux-diagnosability)
- **Source**: M9 finding F2 — the detour costs ~11 actions vs ~6 (Sonarr's inline picker pattern).

#### Scenario: First-run add without leaving the dialog

- **WHEN** the operator opens the add dialog with zero root folders, enters a valid path inline, and registers it
- **THEN** the dialog becomes addable immediately (root folder selected), the search results are still present, and the series can be added without re-searching

#### Scenario: Invalid path surfaces the API's reason

- **WHEN** the inline registration is refused (e.g. not writable)
- **THEN** the dialog shows the refusal verbatim and the operator can correct the path

### Requirement: FRG-UI-035 — Calendar degraded-source notice

WHEN the weekly pull source's health is non-OK, the Calendar SHALL show an inline notice that the external source is unavailable and the view is rendering from local library data only; the notice SHALL NOT render when the source is healthy or deliberately disabled.

- **Milestone**: M9 (m9-ux-diagnosability)
- **Source**: M9 finding F16 — a real upstream outage rendered as a plain "0 issues this week", reading as "nothing ships".

#### Scenario: Outage is visible on the Calendar

- **WHEN** the pull source is degraded and the Calendar renders
- **THEN** an inline notice says the weekly source is unavailable and results come from the local library alone

#### Scenario: Healthy or opted-out renders no notice

- **WHEN** the source is healthy, or `pull_enabled` is false
- **THEN** no degraded notice renders

### Requirement: FRG-UI-036 — Unknown routes render a not-found screen

WHEN the SPA is navigated to a route it does not define, it SHALL render the application shell with a not-found screen linking back to the library, never a blank page.

- **Milestone**: M9 (m9-ux-diagnosability)
- **Source**: M9 finding F3 (`/settings/media` rendered fully blank).

#### Scenario: Unknown route

- **WHEN** the browser loads an undefined path (e.g. `/settings/media`)
- **THEN** the app shell renders with a not-found message and a link to the library

### Requirement: FRG-UI-037 — Completed downloads awaiting import are visible in Queue

WHEN a tracked download has completed in the download client but its import has not yet run (the track-downloads interval has not elapsed), the Queue SHALL show the item in an explicit awaiting-import state rather than showing an empty queue mid-pipeline.

- **Milestone**: M9 (m9-ux-diagnosability)
- **Source**: M9 finding F19 — a fast grab finished inside one 60s tick; the Queue looked empty while the file sat complete and unimported.

#### Scenario: Fast download is never invisible

- **WHEN** the download client reports an item complete and foragerr has not yet imported it
- **THEN** the Queue lists the item with an awaiting-import status until the import runs

### Requirement: FRG-UI-038 — Automated accessibility conformance of core screens

The web UI's core screens SHALL pass the axe-core WCAG 2.1 A/AA automated ruleset with zero serious- or critical-impact violations. In particular: status indicators expose their state through permitted ARIA (the connection indicator is screen-reader-perceivable), text meets the 4.5:1 contrast minimum (sidebar group labels, footer), interactive controls are not nested inside other interactive controls (provider cards), and scrollable regions are keyboard-reachable (Health components table).

- **Milestone**: M9 (m9-a11y-fixes)
- **Source**: Post-cycle axe scan of v0.9.13 (owner-directed, 2026-07-16): 4 serious rules across 21 screens, all in shared components.
- **Notes**: Automated-ruleset conformance is the pinned floor, not a full a11y audit claim — manual audit (screen-reader walkthroughs, focus-order review) remains future work and is NOT asserted by this requirement.

#### Scenario: Shared components carry valid, sufficient semantics

- **WHEN** the app shell renders with a live connection
- **THEN** the connection indicator exposes its state via a role-appropriate ARIA construct, sidebar group labels and footer text meet 4.5:1 contrast, provider cards contain no focusable descendants inside an interactive wrapper, and the Health components table is keyboard-scrollable

#### Scenario: Zero serious violations on the core screens

- **WHEN** the axe-core WCAG 2.1 A/AA ruleset runs against each authenticated core screen
- **THEN** no serious- or critical-impact violations are reported
