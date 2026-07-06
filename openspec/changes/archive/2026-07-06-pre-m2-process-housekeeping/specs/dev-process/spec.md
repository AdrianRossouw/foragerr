# dev-process Spec Delta

## ADDED Requirements

### Requirement: FRG-PROC-013 — Release tagging

Every change merged to `main` from change 7 (`m1-ui-opds-deploy`) onward SHALL be
marked by an annotated git tag on its merge commit, following SemVer: completing a
milestone sets the MINOR line (M1 = 0.1.x, M2 = 0.2.x, M3 = 0.3.x) and each
subsequent merged change within a milestone increments PATCH. The first tag SHALL be
`v0.1.0` at change 7's merge (M1 feature-complete) and `v0.1.1` at change 8's merge
(M1 acceptance-certified). The tag message SHALL name the change id and the FRG
requirement refs the change implements. Tags — together with the `main` branch they
point into — SHALL be pushed to `origin` when created, so every tag is a restore
point that survives loss of the working environment. Tags SHALL never be moved or
deleted once pushed; a bad release is corrected by a new PATCH tag.

#### Scenario: Change merge creates a tag

- **WHEN** a change merges to `main` at or after change 7
- **THEN** the merge gate creates an annotated SemVer tag on the merge commit whose message names the change id and its FRG refs

#### Scenario: Tags are pushed restore points

- **WHEN** a tag is created
- **THEN** the tag and `main` are pushed to `origin` in the same gate, and checking out the tag reproduces the released tree

#### Scenario: Tags are immutable

- **WHEN** a defect is found in a tagged release
- **THEN** the fix lands as a new merged change with a new PATCH tag; the existing tag is never moved or deleted

## MODIFIED Requirements

### Requirement: FRG-PROC-012 — SOUP register

The project SHALL maintain a SOUP (Software of Unknown Provenance) register in
`docs/security/soup-register.md` listing every direct third-party **runtime**
dependency of the backend and frontend with: name, version constraint, source,
intended purpose, the requirements or subsystems it supports, and license.
Development/test-only tooling SHALL be listed in a separate tools section (name,
version constraint, purpose). Any change that adds, removes, or upgrades a
dependency SHALL update the register within the same change. Register-vs-manifest
consistency SHALL be verified mechanically by `tools/soup_check.py`, which SHALL
exit non-zero on drift and SHALL pass at every merge gate.

Systematic known-anomaly/vulnerability review of register items is **deferred as a
documented future improvement**: it SHALL be performed with live advisory tooling
(e.g. `pip-audit`, `npm audit`, GitHub Dependabot) once the project has
network-connected CI, and the register's methodology note SHALL state this posture.
Until then the register SHALL NOT carry per-item anomaly-review verdicts —
knowledge-based (non-live) vulnerability assessments are prohibited as
audit-misleading; the anomaly column reads "Deferred — see methodology".

#### Scenario: Dependency added or upgraded

- **WHEN** a change adds, removes, or upgrades a direct dependency in `pyproject.toml` or `package.json`
- **THEN** the same change updates the corresponding SOUP register row (inventory fields only; no anomaly verdict is fabricated)

#### Scenario: Drift blocks the gate

- **WHEN** `tools/soup_check.py` finds a direct manifest dependency without a matching register row, a register row without a manifest entry, or a version-constraint mismatch
- **THEN** it exits non-zero and the merge gate blocks until the register is reconciled

#### Scenario: Lockfile remains the authoritative pin

- **WHEN** transitive dependencies change solely via lockfile resolution, with no direct-dependency change
- **THEN** no register update is required; the lockfile remains the authoritative pin of the full tree

#### Scenario: Anomaly review activates with network CI

- **WHEN** network-connected CI capable of live advisory queries becomes available
- **THEN** systematic anomaly review is introduced (tooling, cadence, and recording format), and the methodology note is updated from the deferred posture in the same change
