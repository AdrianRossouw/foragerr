# ui — delta for read-only-library

## ADDED Requirements

### Requirement: FRG-UI-045 — Read-only library treatment

The UI SHALL mark read-only roots and their series as read-only, and SHALL
hide or disable every action the backend refuses for them — the monitor
toggle, "search"/grab, and file-mutating actions (delete-files, rename,
move) — so the operator is never offered an action that will be refused.
The root-folder add form SHALL offer a read-only option. Reading and OPDS
browsing of a read-only series SHALL be unaffected.

- **Milestone**: B (read-only-library).
- **Source**: rig finding #4; keeps the acquisition affordances (which a
  read-only series cannot honor) from misleading the operator.
- **Notes**: Purely a suppression/marking layer over FRG-SER-021/022 —
  the backend refuses regardless (fail-closed), so the UI is convenience
  and honesty, not the safety boundary.

#### Scenario: A read-only series offers no acquisition or file actions

- **WHEN** a series on a read-only root is shown
- **THEN** it carries a read-only marker and exposes no monitor toggle, no
  search/grab, and no delete-files/rename/move affordance — while its
  reading and OPDS access are unchanged

#### Scenario: The root-folder form offers read-only registration

- **WHEN** the operator adds a root folder
- **THEN** the form offers a read-only option, and a root registered
  read-only is listed marked as such
