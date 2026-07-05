# dev-process Spec Delta

## ADDED Requirements

### Requirement: FRG-PROC-011 — Manual kept in sync with the application

The project SHALL maintain a user and administrator manual in `docs/manual/`, covering
user-facing behavior (what the application does and how to operate it) and
administration (deployment, configuration, environment variables, network exposure).
Every OpenSpec change proposal SHALL declare its manual impact — the manual sections it
adds or updates, or an explicit "no manual impact" statement with rationale. A change
that alters manual-documented behavior SHALL update the affected manual sections within
the same change, before it merges to `main`, and the merge gate SHALL verify that the
declared manual impact was carried out.

#### Scenario: Change alters documented behavior

- **WHEN** a change alters or adds user-facing or administrative behavior
- **THEN** the same change updates the affected `docs/manual/` sections before the change merges to `main`

#### Scenario: Manual impact declared at proposal time

- **WHEN** an OpenSpec change proposal is authored
- **THEN** it contains a manual-impact declaration (sections touched, or "none" with rationale), reviewable at the FRG-PROC-009 approval gate

#### Scenario: Gate verifies sync

- **WHEN** a change reaches its merge gate
- **THEN** the gate confirms the manual matches the change's declared manual impact, and a mismatch blocks the merge until resolved
