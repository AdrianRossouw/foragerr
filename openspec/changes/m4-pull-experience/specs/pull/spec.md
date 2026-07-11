# Delta: pull — m4-pull-experience

## MODIFIED Requirements

### Requirement: FRG-PULL-007 — Pull view actions

The pull/weekly view SHALL expose per-entry actions for entries **linked to a
library issue** (`matched_issue_id` set): toggle monitored (want/skip) and
trigger an immediate search. Each action SHALL delegate to the canonical
issue-level operation — the single-issue monitored update
(`PUT /api/v1/issues/{issue_id}`, FRG-API-004) and the `issue-search` command
(FRG-SRCH-008) via the command endpoint — and SHALL NOT write any pull-side
status (D4): the card's displayed state changes only because the issue/queue
projection changed. Entries without a linked issue (unmatched, new-series,
pending-refresh) SHALL NOT expose these actions.

- **Milestone**: M4
- **Source**: mylar-feature-surface.md capability map PULL (manual
  want/skip/search from the pull view); sonarr-architecture.md §8 (derived
  state); FRG-API-019 notes (actions delegate to issue endpoints; the pull
  endpoint stays read-only).
- **Notes**: D4. Reuses the existing frontend seams: the single-issue
  monitored mutation and the generic command dispatch + watcher used by the
  Wanted screen. Search completion invalidates the pull query so the card's
  derived state updates.

#### Scenario: Want toggles the linked issue's monitored flag

- **WHEN** the user clicks "want" on a pull entry linked to an unmonitored
  library issue
- **THEN** the client issues `PUT /api/v1/issues/{issue_id}` with
  `monitored: true`, no pull-entry field is written, and the card's state
  re-projects to missing/wanted

#### Scenario: Search queues the canonical issue-search command

- **WHEN** the user triggers search on a linked pull entry
- **THEN** an `issue-search` command is dispatched with that issue's
  `series_id` and `issue_id` through the standard command endpoint, and its
  terminal status invalidates the pull view so derived state refreshes

#### Scenario: Unlinked entries expose no issue actions

- **WHEN** an unmatched or new-series entry (no `matched_issue_id`) renders
- **THEN** it offers no want/skip or search affordance (a new-series entry
  offers the FRG-PULL-008 add affordance instead)

### Requirement: FRG-PULL-008 — New-series surfacing (no auto-add)

The system SHALL surface pull entries tagged `new_series` (issue #1/#0 debuts
not in the library, FRG-PULL-004) for the viewed week as a **distinct "New
this week" list**, separate from the day-grouped agenda, each with a one-click
add affordance that routes into the standard Add flow with the series name
prefilled. The system SHALL NOT add a series automatically: no series record
exists until the user completes the standard add flow, and dismissing or
ignoring the list has no side effects.

- **Milestone**: M4
- **Source**: mylar-feature-surface.md §1 (future_check auto-add) and
  capability map PULL (auto-add of new #1s).
- **Notes**: Deliberate divergence: Mylar auto-adds via fuzzy CV search —
  wrong-match risk and unbounded library growth for a single-user tool.
  Surfacing keeps the discovery value. The add affordance reuses the
  existing Add-screen prefill navigation seam (the same one the header
  quick-search fall-through uses), so matching/config/monitoring decisions
  all happen in the standard, user-driven add flow.

#### Scenario: New #1 appears in the strip with an add affordance

- **WHEN** the viewed week's projection contains a `new_series` entry
- **THEN** the Calendar shows it in a distinct "New this week" list with
  series name, issue and publisher, plus an add affordance — and no series
  record exists in the library

#### Scenario: One-click add routes into the standard add flow prefilled

- **WHEN** the user activates the add affordance on a new-series entry
- **THEN** the client navigates to the Add screen with the entry's series
  name prefilled (standard prefill seam), and any series created results
  from the user completing that flow — never from the pull side

#### Scenario: No new-series entries, no strip

- **WHEN** the viewed week has no `new_series` entries (or they are filtered
  out by the publisher filter)
- **THEN** the "New this week" list is absent entirely rather than rendered
  empty

### Requirement: FRG-PULL-009 — Future/solicited releases

The system SHALL fetch and retain pull-source entries for the **next** ISO
week, in addition to the current and previous weeks, when the source provides
them: the pull-refresh run requests the future week and stores its entries
through the same idempotent per-week replace and matching pipeline
(FRG-PULL-003/004). A future week for which the source has no data yet (a
documented bad-date/619 response or an empty payload) SHALL be skipped with a
logged note without affecting the run's handling of the current and previous
weeks. The weekly view's forward navigation SHALL then include watched-series
matches for the future week, presented as not-yet-released; monitoring/search
behavior for such issues is unchanged (derived state, FRG-PULL-005's
refresh-trigger path applies as usual).

- **Milestone**: M4
- **Source**: mylar-feature-surface.md §1 (futureupcoming) and capability map
  PULL (future-release watching); FRG-PULL-002 ("at least the current and
  previous release weeks" — this widens the window without amending it).
- **Notes**: Thin by design: with derived wanted, "watching" a future issue
  is just monitoring it once refresh creates it — no `add2futurewatchlist`
  machinery. No storage change: `pull_entries` already keys by `(week,
  entry_identity)`; only the command's fetch window changes. The re-poll
  throttle and cadence (FRG-PULL-006) are untouched.

#### Scenario: Refresh stores next-week entries when the source provides them

- **WHEN** a pull refresh runs and the source returns data for the next ISO
  week
- **THEN** those entries are stored under that week's key via the standard
  replace-on-refresh transaction and matched like any other week, and a
  repeat refresh is idempotent for that week

#### Scenario: Future week appears in forward navigation, marked unreleased

- **WHEN** a stored future-week entry matches a watched series and the user
  navigates the Calendar to that week
- **THEN** the entry appears in that week's agenda marked not-yet-released,
  with derived state from the issue/queue projection as usual

#### Scenario: Source without future data degrades to a skipped week only

- **WHEN** a pull refresh requests the next week and receives a 619
  bad-date response (or an empty payload)
- **THEN** the future week is skipped with a logged note, the current and
  previous weeks are still fetched and stored normally, and the run is not
  recorded as an outage
