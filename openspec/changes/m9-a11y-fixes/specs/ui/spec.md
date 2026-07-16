# ui — m9-a11y-fixes deltas

## ADDED Requirements

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
