# Delta: ui — m5-creators-screens

## ADDED Requirements

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
series detail. The profile SHALL render correctly for a creator with no
external bibliography section present (the "More from" section is a later
change); an unknown creator id SHALL render the standard not-found state.

- **Milestone**: M5
- **Source**: design handoff §8 (creator profile region); FRG-API-023
  profile aggregates (whole-series owned/total counts).
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

## MODIFIED Requirements

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
