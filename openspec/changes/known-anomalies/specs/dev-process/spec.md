# dev-process delta — known-anomalies

## ADDED Requirements

### Requirement: FRG-PROC-016 — Known-anomalies register

`docs/security/known-anomalies.md` SHALL record every anomaly the owner
decides to accept rather than fix — a shipped defect, a process deviation, or
an exposure persisting in published artifacts — as an entry with a stable,
never-reused `KA-<NNN>` identifier carrying: a description, the
location/scope, an impact evaluation, the owner's decision with date and
rationale, compensating mitigations, and an explicit review trigger. Entries
SHALL never be deleted: an anomaly later fixed is marked resolved with a
reference to the fixing change. A change whose release accepts a new anomaly
SHALL reference the KA identifier in its release notes. The register is a
controlled document: its structural consistency SHALL be verified by tagged
tests.

#### Scenario: Accepting an anomaly creates a register entry

- **WHEN** the owner decides to accept a defect, deviation, or exposure
  rather than fix it
- **THEN** the register gains a `KA-<NNN>` entry with description,
  location/scope, impact evaluation, owner decision (date + rationale),
  mitigations, and review trigger, in the same change that records the
  decision

#### Scenario: Register consistency is test-enforced

- **WHEN** the documentation-consistency tests run
- **THEN** every register entry has a unique `KA-<NNN>` identifier and all
  required fields, and identifiers are never renumbered or reused

#### Scenario: A fixed anomaly is resolved, not erased

- **WHEN** a previously accepted anomaly is later eliminated by a change
- **THEN** its entry is marked resolved with a reference to that change, and
  the entry (and its identifier) remains in the register permanently
