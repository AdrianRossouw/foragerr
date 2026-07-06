# dev-process Specification

## Purpose

foragerr is built as a demonstration of regulated software development practice. This
capability governs *how* the project is developed: requirement identity, traceability
from requirements to specs, tests, and commits, and security risk management. These
requirements apply to every contributor — human or agent — and are enforced by
tooling wherever possible.
## Requirements
### Requirement: FRG-PROC-001 — Commit traceability

Every commit on any branch SHALL follow the Conventional Commits format and SHALL carry
a `Refs:` trailer listing at least one registered requirement ID that the commit
implements, tests, or documents. Merge and revert commits are exempt. Enforcement SHALL
be automated via a `commit-msg` hook.

#### Scenario: Compliant commit accepted

- **WHEN** a commit message has a valid Conventional Commits subject and a `Refs:` trailer citing IDs present in the requirements registry
- **THEN** the commit-msg hook accepts the commit

#### Scenario: Missing or unknown requirement reference rejected

- **WHEN** a commit message lacks a `Refs:` trailer, or cites an ID absent from the requirements registry
- **THEN** the commit-msg hook rejects the commit with an explanation of the required format

### Requirement: FRG-PROC-002 — Stable requirement identifiers

Every requirement SHALL have a unique identifier of the form `FRG-<AREA>-<NNN>`,
allocated in `docs/traceability/requirements-registry.md` when the requirement is first
proposed. Identifiers SHALL never be reused or renumbered; withdrawn requirements keep
their identifier with status `withdrawn`.

#### Scenario: New requirement is proposed

- **WHEN** a requirement is added to an OpenSpec change proposal
- **THEN** it receives the next free number in its AREA and a `proposed` row in the registry before the proposal is considered reviewable

### Requirement: FRG-PROC-003 — Spec before code

Production code SHALL only be written against requirements that exist in an OpenSpec
change proposal or an archived spec. Changes in behavior SHALL be proposed as OpenSpec
changes (proposal → specs delta → tasks) before implementation begins.

#### Scenario: Behavior change requested

- **WHEN** a new capability or behavior change is requested
- **THEN** an OpenSpec change is authored and its requirements registered before implementation commits are made

### Requirement: FRG-PROC-004 — Requirements verified by tagged tests

Every functional and non-functional requirement SHALL be verified by at least one
automated test that is tagged with the requirement identifier (e.g. a pytest marker or
test docstring reference), so that test results can be mapped back to requirements.

#### Scenario: Requirement implemented

- **WHEN** a requirement's implementation is completed
- **THEN** the test suite contains at least one test tagged with that requirement's ID, and it passes

### Requirement: FRG-PROC-005 — Traceability matrix

The project SHALL maintain a traceability matrix in `docs/traceability/` mapping each
requirement to its spec location, verifying tests, and implementing commits. The matrix
SHALL be regenerable from the repository (registry, test tags, git trailers) rather than
hand-maintained prose.

#### Scenario: Traceability audit

- **WHEN** the traceability matrix is regenerated
- **THEN** every `active` requirement resolves to at least one spec section, one tagged test, and one commit, and gaps are reported explicitly

### Requirement: FRG-PROC-006 — Threat analysis and risk register

The project SHALL maintain a STRIDE-based threat analysis and a living risk register in
`docs/security/`. Each identified risk SHALL be either accepted (with rationale) or
mitigated by one or more registered `FRG-SEC-*` / `FRG-NFR-*` requirements, which are
themselves test-verified per FRG-PROC-004.

#### Scenario: New attack surface added

- **WHEN** a change introduces new attack surface (network listener, parser of untrusted input, credential storage, outbound integration)
- **THEN** the threat analysis and risk register are updated as part of that change, before it is archived

### Requirement: FRG-PROC-007 — Branch-based integration, green main

No commits SHALL be made directly on `main`; all work SHALL happen on branches
(`change/<openspec-change-id>` for spec'd work, `research/<topic>` for research
artifacts, `process/<name>` for governance) and land on `main` only via `--no-ff`
merges, so per-commit `Refs:` trailers survive in history. A merge to `main` SHALL
only occur while the full test suite passes; merged branches SHALL be deleted.
Direct-commit prevention SHALL be automated via a `pre-commit` hook. The Phase 0
bootstrap root commit predates this requirement and is grandfathered. CI
re-enforcement of the green rule is deferred until a CI pipeline exists.

#### Scenario: Direct commit on main rejected

- **WHEN** a commit is attempted while `main` is checked out and no merge is in progress
- **THEN** the pre-commit hook rejects it and directs the author to a branch

#### Scenario: Branch merge accepted

- **WHEN** a branch is merged into `main` with `--no-ff` while the test suite is green
- **THEN** the merge commit is accepted and the branch is deleted after the merge

### Requirement: FRG-PROC-008 — Worktree isolation for concurrent agents

Any agent that mutates repository files SHALL work in its own git worktree on its own
branch, with one writer per file area; the orchestrator SHALL own all merges, conflict
resolution, and worktree cleanup after the branch merges. Research and analysis agents
SHALL be read-only, returning findings as text for the orchestrator to write.

#### Scenario: Concurrent implementation agents

- **WHEN** two or more file-mutating agents run concurrently
- **THEN** each operates in a distinct worktree and branch, and their work reaches the shared branch only through orchestrator-managed merges

#### Scenario: Research agent output

- **WHEN** a research agent completes its analysis
- **THEN** it has modified no repository files; its findings arrive as returned text that the orchestrator reviews and writes

### Requirement: FRG-PROC-009 — Spec approval gate

No implementation task of an OpenSpec change SHALL begin until the project owner
(Adrian) has explicitly approved the proposal. Approval SHALL be recorded in the
proposal file as an `## Approval` section naming the approver, date, and decision.
Phase transitions SHALL additionally pass through plan-mode gates presenting the
phase plan for approval before phase work (including sub-agent fan-outs) starts.

#### Scenario: Implementation attempted without approval

- **WHEN** implementation work is proposed for a change whose proposal lacks a recorded approval
- **THEN** the work does not proceed; the proposal is presented to the owner for decision first

#### Scenario: Approved change proceeds

- **WHEN** a proposal carries a recorded approval
- **THEN** implementation may begin, scoped to the approved requirements

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

