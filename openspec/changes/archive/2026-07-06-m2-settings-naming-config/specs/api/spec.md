## MODIFIED Requirements

### Requirement: FRG-API-013 — Config resource endpoints

The API SHALL expose typed config resources (host, media management, naming, UI) as GET/PUT singletons so all settings changes flow through the documented API rather than ad-hoc form posts.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §7.1 Config/{host, mediamanagement, naming, ui}; mylar-feature-surface.md §7 (Mylar's 34-section ini — the anti-pattern being replaced).
- **Notes**: `api/config_resources.py` (new). This change lands `config/naming` and `config/mediamanagement`; host/ui arrive with their own reqs. Field-precise 4xx uses the existing uniform shape (`api/errors.py` `ApiError`/`error_body`) with `errors[].field` under a `settings.` prefix. No secret-typed field appears in these resources (secrets remain DEP/AUTH). Persists into `config.yaml` and re-loads `app.state.settings`. Tag test: `tests/api/test_config_resources.py`.

#### Scenario: GET returns the typed current values

- **GIVEN** a running instance
- **WHEN** `GET /api/v1/config/naming` is called
- **THEN** it returns the typed current naming values (file template, folder template, rename toggle, illegal-character policy) with no secret fields present.

#### Scenario: PUT round-trips and takes effect

- **GIVEN** a `PUT /api/v1/config/naming` changing the file template
- **WHEN** a subsequent `GET /api/v1/config/naming` runs and a rename preview is computed
- **THEN** the GET reflects the new template and the preview renders names using it.

#### Scenario: Per-field validation error in the uniform shape

- **GIVEN** a `PUT` carrying an invalid value (a blank required template, or a `recycle_bin_path` that fails confinement/writability)
- **WHEN** it is submitted
- **THEN** the response is a 400 in the `{"message", "errors":[{"field","message"}]}` shape naming the offending setting field, and no config value is changed.

#### Scenario: Media-management resource round-trips its fields

- **GIVEN** the media-management resource
- **WHEN** `PUT /api/v1/config/mediamanagement` sets transfer mode, recycle-bin path, retention days, and import mode, followed by a `GET`
- **THEN** the GET returns those values and the running settings reflect them.

#### Scenario: No secret ever transits these resources

- **GIVEN** the `config/naming` and `config/mediamanagement` schemas
- **WHEN** their fields are audited
- **THEN** no secret-typed field is present in either request or response body.
