# nfr — m9-ux-diagnosability deltas

## ADDED Requirements

### Requirement: FRG-NFR-016 — Library-import group failures logged at WARNING with reasons

WHEN a library-import execution fails or blocks a group, the system SHALL log one WARNING per affected group naming the group and its verbatim reason, in addition to the existing INFO totals, so an operator watching container logs sees actionable causes without opening the UI.

- **Milestone**: M9 (m9-ux-diagnosability)
- **Source**: M9 finding F11 — five failures logged only as `library-import: add-failed=5 blocked=1` at INFO; reasons existed solely as UI card state.
- **Notes**: "Fails or blocks" is read broadly — every non-imported terminal group outcome (add-failed, blocked, partial, refresh-failed, no-folder, duplicate, empty, errored) warns, with "no reason recorded" standing in when a group carries none.

#### Scenario: Failure reasons reach the log

- **WHEN** an import run leaves groups add-failed or blocked
- **THEN** each such group produces a WARNING log record carrying the group identity and its recorded reason
