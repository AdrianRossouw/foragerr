# ui — delta for m11-review-experience

## ADDED Requirements

### Requirement: FRG-UI-039 — Per-row ComicVine search picker

The web UI SHALL offer a free-text ComicVine search on every reviewable
entitlement row, reusing the add-series lookup surface (debounced
suggest, full search, in-library marking, outcome notes incl. budget and
credential guidance): picking an in-library candidate matches the row to
that series; picking one not in the library adds and matches it in a
single action. The search affordance SHALL be present regardless of the
row's proposal state — a "no plausible automatic match" verdict is
displayed as the automatic outcome beside the search, never as a dead
end. The library-only dropdown picker is retired.

#### Scenario: Search resolves a row the proposals could not

- **WHEN** the operator opens the row search on an entitlement with no
  plausible automatic match, types a title, and picks a ComicVine result
  not in the library
- **THEN** the series is added and the entitlement matched to it in that
  single action, and the row leaves review as matched

#### Scenario: In-library result is marked and matches directly

- **WHEN** row-search results include a volume already in the library
- **THEN** that result is visibly marked as in-library and picking it
  matches the entitlement without creating anything

#### Scenario: Search outcome notes match the add screen

- **WHEN** the row search hits the ComicVine budget ceiling or a
  credential failure
- **THEN** the same honest outcome notes the add-series screen shows
  appear in the row search (resume time / credential guidance), and the
  row remains actionable later

## MODIFIED Requirements

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
entitlement rows with format chip, status tag, bundle name, per-status actions, and
an expandable reconcile detail with issue chips per the handoff's edge rules).
Same-title rows SHALL collapse into expandable groups (shared matching-key fold)
with visible counts, and selection helpers SHALL cover a whole bundle and a whole
collapse group alongside the M4 shift-range pattern. The review list SHALL render
virtualized so thousand-row queues stay responsive. Session expiry
SHALL surface as the global banner plus amber header/footer health treatments, and
bulk review actions SHALL support the M4 selection pattern including shift-range
select.

#### Scenario: Connect flow

- **WHEN** the operator opens Sources with no connected store, pastes a cookie of plausible length, and clicks Connect
- **THEN** Connect is disabled until the paste threshold, validation feedback comes from the live check (FRG-SRC-002), and success lands on the manage view with entitlements syncing

#### Scenario: Review actions by status

- **WHEN** the operator works the entitlement list
- **THEN** New rows offer the proposal action (match or add per FRG-SRC-010), the row ComicVine search (FRG-UI-039), and Ignore; Matched rows offer Change (via the same search) / Ignore; Ignored rows are dimmed with Restore; the filter counts stay live; and expanding a row shows the reconcile explanation with issue chips (amber = owned single; suppressed above 12 issues)

#### Scenario: Expiry surfaces globally

- **WHEN** a connected source's session expires while the operator is anywhere in the app
- **THEN** the global banner appears with a Reconnect action, the sidebar footer and header health icon turn amber, the Sources badge shows `!`, and reconnecting (from banner or card) clears all three

#### Scenario: No unreviewed-count badge on the nav

- **WHEN** a connected source has unreviewed `new` entitlements but no expiry
- **THEN** the Sources nav item shows no count badge; the pending-review counts appear only on the Sources page (the manage view's count line and All/New/Matched/Ignored filter), where their comic/non-comic scope is visible

#### Scenario: First sync at scale

- **WHEN** the first sync of a long-standing account lands over a thousand new entitlements (the dogfood corpus is 1,318)
- **THEN** the review list renders virtualized and remains responsive, same-title runs collapse into groups with counts (145 same-franchise rows read as one expandable group), bulk select works by shift-range, by bundle, and by group, bulk accept applies each row's own proposal (FRG-SRC-011), and pending counts are accurate

#### Scenario: Collapse never hides actionable state

- **WHEN** rows inside a collapsed group differ in status (some new, one failed download)
- **THEN** the group header surfaces the mixed state (counts by status) and expanding always reaches every row's full actions — collapse is presentation, never a state filter
