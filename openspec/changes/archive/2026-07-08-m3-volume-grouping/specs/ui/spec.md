# ui Spec Delta

## ADDED Requirements

### Requirement: FRG-UI-021 — Grouped library view

The Comics (library index) screen SHALL offer a **grouped** display mode alongside the
existing poster/overview/table modes: franchise groups (FRG-SER-016) rendered as
headers carrying the group title and an aggregated stat roll-up, with their member
runs nested beneath and collapsible, in the current Sonarr-shaped visual style. A
franchise with a single run SHALL render as an ordinary row (no empty group chrome).
The mode SHALL be a toggle in the existing library view state; switching to it SHALL
not change series identity, monitoring, or any per-series action, and the flat views
SHALL remain available and unchanged. From the grouped view the operator SHALL be able
to reach the group rename / series-reassign affordance (FRG-SER-017).

#### Scenario: Grouped mode nests runs under franchise headers

- **WHEN** the operator switches the Comics screen to grouped mode with multiple runs of one title
- **THEN** the runs appear nested under one collapsible franchise header with a roll-up stat, and single-run franchises render as ordinary rows

#### Scenario: Grouping is display-only

- **WHEN** the grouped view is shown
- **THEN** per-series monitored state, actions, and navigation behave exactly as in the flat views, and toggling back to a flat view shows the same series unchanged

#### Scenario: Correcting a group from the view

- **WHEN** the operator renames a group or reassigns a run from the grouped view
- **THEN** the change persists (FRG-SER-017) and the view reflects the corrected grouping
