# ui — delta for m11-review-refinements

## ADDED Requirements

### Requirement: FRG-UI-043 — Group-header search/match affordance

The collapsed source-review group header SHALL offer a search/match
affordance — a picker seeded with the group's title — so an operator can
resolve a whole `group_key` group in one action rather than row by row.
Picking a candidate already in the library SHALL bulk-match every member
of the group to it; picking a candidate not yet in the library SHALL add
it once and leave the remaining members as swept proposals (FRG-SRC-014)
for a single bulk accept. The affordance SHALL sit alongside the existing
header controls (select-all, collapse toggle) and SHALL reuse the
per-row search picker's presentation and behavior (FRG-UI-039), differing
only in that it applies to the group's members rather than one row.

- **Milestone**: M11 (m11-review-refinements).
- **Source**: rig dogfood 2026-07-28 (a 145-row group requires 145
  identical picks); builds on the change-2 group collapse (FRG-UI-029)
  and per-row search (FRG-UI-039).
- **Notes**: The group's member ids come from the already-rendered
  `group.rows`, so the client supplies the id list — no server-side
  `group_key` filter is needed for the bulk apply.

#### Scenario: The group header offers a search/match picker

- **WHEN** a collapsed review group is shown
- **THEN** its header offers a search/match affordance seeded with the
  group's title, beside the select-all and collapse controls

#### Scenario: Picking an in-library candidate matches the whole group

- **WHEN** the operator picks a candidate that is already in the library
  from the group-header picker
- **THEN** every member of the group is matched to that series in one
  action

#### Scenario: Picking a new candidate adds once and proposes the rest

- **WHEN** the operator picks a candidate not yet in the library
- **THEN** the series is added once and the remaining group members
  become swept proposals (FRG-SRC-014) resolvable with a single bulk
  accept — no member is committed without the operator's accept

### Requirement: FRG-UI-044 — Force-grab affordance for rejected releases

The interactive search results SHALL offer a "Grab anyway" affordance on
rejected and temporarily-rejected releases, distinct from the ordinary
Grab on approved releases and gated behind an explicit confirm step
(because it bypasses the quality rules). Activating it SHALL send the
grab with `force: true` (FRG-API-008) through the existing grab path.
Approved releases SHALL keep their ordinary one-click Grab with no
confirm. The rejection reasons SHALL remain visible so the operator sees
what they are overriding.

- **Milestone**: M11 (m11-review-refinements).
- **Source**: rig dogfood 2026-07-28 (the "Absolute Green Lantern" case —
  a wanted release exists but every candidate is rejected, leaving no
  grab).
- **Notes**: Reuses the existing grab mutation unchanged apart from the
  `force` flag; the server enforces the approval gate (FRG-API-008), so
  the button is a deliberate, audited override, not a client-only bypass.

#### Scenario: Rejected releases offer a confirmed Grab-anyway

- **WHEN** an interactive search returns releases that are all rejected
- **THEN** each rejected row offers a "Grab anyway" affordance that,
  after an explicit confirm, grabs it with `force: true`, and the row's
  rejection reasons stay visible

#### Scenario: Approved releases are unchanged

- **WHEN** a search returns approved releases
- **THEN** they keep the ordinary one-click Grab with no confirm step
  and no force flag
