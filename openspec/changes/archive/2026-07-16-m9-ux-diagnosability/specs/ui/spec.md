# ui — m9-ux-diagnosability deltas

## ADDED Requirements

### Requirement: FRG-UI-033 — Actionable UI-language guidance with settings links

WHEN the web UI shows guidance or an error that names a settings destination (e.g. the ComicVine-key error, the add dialog's root-folder notice), the destination SHALL be rendered as a navigable link to that settings screen, and UI-facing warning/health copy SHALL speak in UI terms (screen names and labels) rather than configuration-key names — config keys stay in logs and admin docs.

- **Milestone**: M9 (m9-ux-diagnosability)
- **Source**: M9 findings F2 and F4 (`docs/research/m9-user-sim-findings.md`).
- **Notes**: Sweep-scoped: the two named surfaces plus the pull-source health remediation (which told a UI user to "verify 'pull_source_url'").

#### Scenario: Credential error links to Settings

- **WHEN** an Add New search fails for a missing/invalid ComicVine key
- **THEN** the guidance names Settings → General as a link that navigates there

#### Scenario: Health remediation speaks UI language

- **WHEN** the weekly pull source is degraded and its health warning renders in the UI
- **THEN** the remediation text names UI surfaces (not raw config-key names)

### Requirement: FRG-UI-034 — Inline root-folder creation in the add dialog

WHEN no root folder is registered and the operator opens the add-series dialog, the dialog SHALL offer registering a root folder inline (path input through the same validated API), and on success SHALL proceed with the add flow without abandoning the dialog or losing the search results.

- **Milestone**: M9 (m9-ux-diagnosability)
- **Source**: M9 finding F2 — the detour costs ~11 actions vs ~6 (Sonarr's inline picker pattern).

#### Scenario: First-run add without leaving the dialog

- **WHEN** the operator opens the add dialog with zero root folders, enters a valid path inline, and registers it
- **THEN** the dialog becomes addable immediately (root folder selected), the search results are still present, and the series can be added without re-searching

#### Scenario: Invalid path surfaces the API's reason

- **WHEN** the inline registration is refused (e.g. not writable)
- **THEN** the dialog shows the refusal verbatim and the operator can correct the path

### Requirement: FRG-UI-035 — Calendar degraded-source notice

WHEN the weekly pull source's health is non-OK, the Calendar SHALL show an inline notice that the external source is unavailable and the view is rendering from local library data only; the notice SHALL NOT render when the source is healthy or deliberately disabled.

- **Milestone**: M9 (m9-ux-diagnosability)
- **Source**: M9 finding F16 — a real upstream outage rendered as a plain "0 issues this week", reading as "nothing ships".

#### Scenario: Outage is visible on the Calendar

- **WHEN** the pull source is degraded and the Calendar renders
- **THEN** an inline notice says the weekly source is unavailable and results come from the local library alone

#### Scenario: Healthy or opted-out renders no notice

- **WHEN** the source is healthy, or `pull_enabled` is false
- **THEN** no degraded notice renders

### Requirement: FRG-UI-036 — Unknown routes render a not-found screen

WHEN the SPA is navigated to a route it does not define, it SHALL render the application shell with a not-found screen linking back to the library, never a blank page.

- **Milestone**: M9 (m9-ux-diagnosability)
- **Source**: M9 finding F3 (`/settings/media` rendered fully blank).

#### Scenario: Unknown route

- **WHEN** the browser loads an undefined path (e.g. `/settings/media`)
- **THEN** the app shell renders with a not-found message and a link to the library

### Requirement: FRG-UI-037 — Completed downloads awaiting import are visible in Queue

WHEN a tracked download has completed in the download client but its import has not yet run (the track-downloads interval has not elapsed), the Queue SHALL show the item in an explicit awaiting-import state rather than showing an empty queue mid-pipeline.

- **Milestone**: M9 (m9-ux-diagnosability)
- **Source**: M9 finding F19 — a fast grab finished inside one 60s tick; the Queue looked empty while the file sat complete and unimported.

#### Scenario: Fast download is never invisible

- **WHEN** the download client reports an item complete and foragerr has not yet imported it
- **THEN** the Queue lists the item with an awaiting-import status until the import runs
