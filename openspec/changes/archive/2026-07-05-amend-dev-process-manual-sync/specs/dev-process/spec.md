# dev-process Spec Delta

## ADDED Requirements

### Requirement: FRG-PROC-011 — Manual kept in sync with the application

The project SHALL maintain a user and administrator manual in `docs/manual/`, covering
user-facing behavior (what the application does and how to operate it) and
administration (deployment, configuration, environment variables, network exposure),
together with the repository `README.md` as top-level labelling/technical
documentation stating what the project is, its security and regulatory posture, the
development process (way of working), and installation instructions once the
deployment surface exists. Every OpenSpec change proposal SHALL declare its manual
impact — the manual/README sections it adds or updates, or an explicit "no manual
impact" statement with rationale. A change that alters manual-documented behavior
SHALL update the affected sections within the same change, before it merges to `main`,
and the merge gate SHALL verify that the declared manual impact was carried out.

#### Scenario: Change alters documented behavior

- **WHEN** a change alters or adds user-facing or administrative behavior
- **THEN** the same change updates the affected `docs/manual/` sections before the change merges to `main`

#### Scenario: Manual impact declared at proposal time

- **WHEN** an OpenSpec change proposal is authored
- **THEN** it contains a manual-impact declaration (sections touched, or "none" with rationale), reviewable at the FRG-PROC-009 approval gate

#### Scenario: Gate verifies sync

- **WHEN** a change reaches its merge gate
- **THEN** the gate confirms the manual matches the change's declared manual impact, and a mismatch blocks the merge until resolved

### Requirement: FRG-PROC-012 — SOUP register

The project SHALL maintain a SOUP (Software of Unknown Provenance) register in
`docs/security/soup-register.md` listing every direct third-party **runtime**
dependency of the backend and frontend with: name, version constraint, source,
intended purpose, the requirements or subsystems it supports, license, and a
known-anomaly review note (date and outcome). Development/test-only tooling SHALL be
listed in a separate tools section (name, version constraint, purpose). Any change
that adds, removes, or upgrades a dependency SHALL update the register within the same
change. Register-vs-manifest consistency SHALL be verified mechanically by
`tools/soup_check.py`, which SHALL exit non-zero on drift and SHALL pass at every
merge gate.

#### Scenario: Dependency added or upgraded

- **WHEN** a change adds, removes, or upgrades a direct dependency in `pyproject.toml` or `package.json`
- **THEN** the same change updates the corresponding SOUP register row, including a dated known-anomaly review note for additions and upgrades

#### Scenario: Drift blocks the gate

- **WHEN** `tools/soup_check.py` finds a direct manifest dependency without a matching register row, a register row without a manifest entry, or a version-constraint mismatch
- **THEN** it exits non-zero and the merge gate blocks until the register is reconciled

#### Scenario: Lockfile remains the authoritative pin

- **WHEN** transitive dependencies change solely via lockfile resolution, with no direct-dependency change
- **THEN** no register update is required; the lockfile remains the authoritative pin of the full tree
