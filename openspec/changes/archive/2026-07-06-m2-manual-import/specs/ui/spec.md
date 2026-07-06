## MODIFIED Requirements

### Requirement: FRG-UI-014 — Manual import overlay

The UI SHALL provide a manual-import overlay (reachable from ImportBlocked queue items and from a path picker) listing candidate files with their would-be decisions and rejection reasons, allowing per-file override of series, issue, and format before importing.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §5.5 manual import, §4.5 ImportBlocked → ManualInteractionRequiredEvent, §7.4 InteractiveImport overlay.
- **Notes**: Depends on the API manual-import endpoint. Design-school reference is `InteractiveSearchOverlay` (Modal, decision chip + Popover of verbatim reasons, no client-side re-sorting).

#### Scenario: Reachable from an ImportBlocked queue row

- **WHEN** the user opens "Manual import" on an `import_blocked` queue row
- **THEN** the overlay opens for that download, lists its candidate files with decision chips and verbatim rejection reasons, and imports the file end-to-end into the library once a valid override is applied.

#### Scenario: Reachable from a path picker

- **WHEN** the user opens manual import via the path picker and selects a folder
- **THEN** the overlay lists that folder's archives with their would-be decisions and per-file override controls.

#### Scenario: Per-file override controls, pre-filled

- **WHEN** a candidate row renders
- **THEN** it shows series/issue/format controls pre-filled from the API's suggested values; the issue picker is scoped to the chosen series; and a verified embedded ComicInfo suggestion is badged as such.

#### Scenario: Verbatim reasons for blocked rows

- **WHEN** a candidate's would-be decision is blocked
- **THEN** its reasons render verbatim (as returned) via the decision popover — never paraphrased or re-ordered client-side.

#### Scenario: Submit and reflect outcome

- **WHEN** the user imports the selected files
- **THEN** the overlay posts the corrected mappings, and on completion the imported files leave the list while any still-blocked files re-render with their updated reasons; the queue view refreshes.
