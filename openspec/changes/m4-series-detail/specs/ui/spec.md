# ui delta — m4-series-detail

## MODIFIED Requirements

### Requirement: FRG-UI-004 — Series detail screen

The UI SHALL provide a series detail screen rendered to the M4 design: a
hero whose backdrop is the series cover blurred and darkened (gradient into
the page background) behind the sharp 2:3 cover (~206×309) and metadata —
title, book-type/volume badge where applicable, a meta row (monitored
state, publisher, first-issue date, status, issue count, file formats), an
icon-over-label action row (Search Monitored, Search All, Refresh, Edit,
Delete with optional file removal — all dispatching the existing
commands), and the overview paragraph, which SHALL collapse behind a
"show more" toggle when it overflows its clamp. Below the hero a bordered
panel SHALL carry an `Issues · N / Collections · N` segmented toggle and a
compact owned/total progress bar; the Issues tab is a dense table —
selection checkbox (FRG-UI-025), per-issue monitored toggle, verbatim
issue number, release date, status pill (file present = success, missing =
warn, unreleased = neutral), collected-in chips (FRG-SER-020 memberships,
book-type-toned), file size, and per-row automatic + interactive search
actions. Covers come exclusively from the local cover endpoint, including
the backdrop.

- **Milestone**: M1 (redesigned to the owner's design in M4,
  m4-series-detail)
- **Source**: sonarr-architecture.md §7.4 (Series details), §7.2 command
  endpoint; owner design handoff §2, reviewed 2026-07-10.
- **Notes**: The M4 redesign supersedes the M1 visual language; command
  dispatch, per-issue monitor semantics, verbatim issue numbers
  (never coerced), and the e2e selector contract (`issue-row-<issueId>`,
  per-row search accessible names, `interactive-search-overlay`,
  `command-status`) are unchanged. Creator credits await M5.

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

## ADDED Requirements

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
