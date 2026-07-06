## MODIFIED Requirements

### Requirement: FRG-UI-012 — Settings: media management and naming with rename preview

The UI SHALL provide media-management/naming settings (rename on/off, folder and file templates with token help, illegal-character policy, root folders) with a live preview showing example output for the current template and a per-series rename preview (existing → new paths) before execution.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §5.4 naming engine ("Rename is previewable"), §7.1 Config/naming; mylar-feature-surface.md §PP (FILE_FORMAT/FOLDER_FORMAT tokens); docs/research/sonarr-ui §10 (media-management screen: monospace template inputs, live "Example:" line, `?` token popover, save-bar model).
- **Notes**: Bespoke single-form settings page (not the provider list+modal machinery), reusing the `components/schemaForm/SchemaForm` field renderer for standard fields plus two bespoke panels — the live example preview and the per-series rename-preview table (design decision 11). Token help renders from one shared vocabulary (`renamer._TOKEN_ALIASES`). Field errors reuse the `settings.`-prefix `mapApiError` mapping. Tag test: `frontend/src/screens/settings/MediaManagement.test.tsx` + an e2e for the preview→confirm flow.

#### Scenario: Live example recomputes as the template is edited

- **GIVEN** the media-management settings page open on a fixture series
- **WHEN** the user edits the file template
- **THEN** the example filename shown under the input recomputes live from the shared token vocabulary without a round-trip to save.

#### Scenario: Per-series rename preview applies only on confirm

- **GIVEN** a series with library files whose names differ from the current template
- **WHEN** the user opens the rename preview
- **THEN** the panel lists old→new diffs, no filesystem change occurs until the user confirms, and confirming invokes the execute endpoint.

#### Scenario: Token help popover from the shared vocabulary

- **GIVEN** the `?` affordance beside a template input
- **WHEN** it is activated
- **THEN** a token cheatsheet renders every supported token from the one shared definition (no hand-maintained duplicate list).

#### Scenario: Standard fields render via SchemaForm and persist on save

- **GIVEN** the page's rename toggle, illegal-character policy, transfer mode, import mode, and recycle-bin path + retention fields
- **WHEN** the user changes one and uses the save-bar
- **THEN** the field is rendered by the shared `SchemaForm` renderer and the change persists through the config `PUT` endpoint.

#### Scenario: Field-precise validation error attaches to its field

- **GIVEN** an invalid submission (e.g. a blank template or a non-confinable recycle-bin path)
- **WHEN** save returns a field-precise 4xx in the uniform error shape
- **THEN** the error is displayed against the offending field via the `settings.`-prefix `mapApiError` mapping, not as a bare form error.
