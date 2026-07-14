# Spec Delta: ui (wanted-count-consistency)

## MODIFIED Requirements

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
