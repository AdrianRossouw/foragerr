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
