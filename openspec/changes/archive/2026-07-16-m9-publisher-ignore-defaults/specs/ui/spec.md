# ui — m9-publisher-ignore-defaults deltas

## ADDED Requirements

### Requirement: FRG-UI-031 — Ignored publishers editable in Settings

Settings → General SHALL expose the ComicVine ignored-publishers list for viewing and editing (comma-separated, wildcard entries permitted), persisting through the same validated config writer as other file-persisted settings and applying to subsequent searches without restart. When the value is environment-managed (`FORAGERR_COMICVINE_IGNORED_PUBLISHERS` set), the field SHALL render read-only with an environment-managed indication, mirroring the ComicVine key pattern.

- **Milestone**: M9 (m9-publisher-ignore-defaults)
- **Source**: M9 finding F17 recommendation; owner approval 2026-07-16. The setting existed since M1 but was config-file-only.
- **Notes**: The value is not a secret — unlike the key field it echoes its current value for editing. Env-wins precedence is the standard settings rule, surfaced rather than silently ignored.

#### Scenario: Edit and apply without restart

- **WHEN** the operator edits the ignored-publishers list in Settings → General and saves
- **THEN** the value is validated, persisted to `config.yaml`, and the next Add New search applies the updated list with no restart

#### Scenario: Environment-managed value is read-only

- **WHEN** `FORAGERR_COMICVINE_IGNORED_PUBLISHERS` is set in the environment
- **THEN** the Settings field shows the effective value read-only with an environment-managed note, and writes to it are refused

### Requirement: FRG-UI-032 — Hidden-by-ignore-list results are recoverable in Add New

WHEN an Add New search excludes results via the publisher ignore list, the screen SHALL show an explicit count of hidden results with a one-click control that reveals them (flagged as ignore-listed) for that search, together with a path to edit the list in Settings. Nothing is silently dropped; revealing is per-search and does not modify the configured list.

- **Milestone**: M9 (m9-publisher-ignore-defaults)
- **Source**: M9 finding F17; owner approval 2026-07-16 — the recoverable form is what makes a shipped default acceptable (vs Mylar's silent drop).
- **Notes**: Reveal refetches with the include-ignored query mode (FRG-META-007) and badges the ignore-listed candidates; the count line renders only when the count is non-zero.

#### Scenario: Hidden count with one-click reveal

- **WHEN** a search excludes N > 0 results via the ignore list
- **THEN** the results view shows "N result(s) hidden by your publisher ignore list" with a Show control; activating it reveals the hidden candidates, visibly badged, without altering the configured list

#### Scenario: No hidden results, no chrome

- **WHEN** a search excludes nothing
- **THEN** no hidden-results line renders
