# Delta: ui — m4-pull-experience

## MODIFIED Requirements

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
  defaulting to Following. Following shows only entries linked to library
  series (matched or pending-refresh); All releases shows every entry.
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

#### Scenario: Default load shows the current week in Following scope

- **WHEN** the Calendar screen loads with no navigation state
- **THEN** it requests the current store-date week (no `week` param needed),
  renders only entries linked to library series grouped by day with the
  range label, and marks Wednesday "New Comic Day" and the current date
  "Today"

#### Scenario: Week navigation is parameterised and reversible

- **WHEN** the user clicks next, then next, then "This Week"
- **THEN** each click re-queries the endpoint with the correct target ISO
  week (+1, +2, then current), the range label follows, and no server-side
  navigation state is involved

#### Scenario: All-releases scope reveals unfollowed entries

- **WHEN** the user switches the scope toggle to "All releases" on a week
  containing both linked and unmatched entries
- **THEN** unmatched entries become visible in their day groups, days show
  their "N followed" count where applicable, and switching back to Following
  hides them again behind a "+N more titles shipping" note

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
