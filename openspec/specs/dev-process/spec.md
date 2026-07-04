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
