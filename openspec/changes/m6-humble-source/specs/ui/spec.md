# ui delta — m6-humble-source

## ADDED Requirements

### Requirement: FRG-UI-027 — Sources screen

The web UI SHALL provide a top-level Sources screen per the v2 design handoff: a
Sources nav item (badge = unreviewed-new count, amber `!` on expiry); a store rail
(connected/expired/not-connected status per store); a connect card for
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
- **THEN** the global banner appears with a Reconnect action, the sidebar footer and header health icon turn amber, the Sources badge flips to `!`, and reconnecting (from banner or card) clears all three

#### Scenario: First sync at scale

- **WHEN** the first sync of a long-standing account lands hundreds of new entitlements
- **THEN** the review list remains responsive, supports bulk select (including shift-range) for accept/ignore, and pending counts are accurate
