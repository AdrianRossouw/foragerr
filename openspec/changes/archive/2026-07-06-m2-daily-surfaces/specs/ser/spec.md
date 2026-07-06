# ser — delta for m2-daily-surfaces

## MODIFIED Requirements

### Requirement: FRG-SER-008 — Root folders and series paths

The system SHALL support one or more configured root folders, manageable through the API — registration (`POST /rootfolder`, validated) and removal (`DELETE /rootfolder/{id}`, refused while series reference it) — each series SHALL have a path defaulting to `<root folder>/<templated series folder>` created on add, with the folder-name template configurable and the path overridable per series.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §1.2 step 1, §5.5 (RootFolderService); mylar-feature-surface.md capability map SER (multiple destination dirs, create-folders-on-add, per-series location).
- **Notes**: Subsumes Mylar's `MULTIPLE_DEST_DIRS` and per-series location + dir lock. Folder *naming* token engine is owned by the import/rename area; SER owns the association. Management endpoints added in m2-daily-surfaces: registration was previously unreachable outside direct DB seeding (a first-run blocker found in live testing — no series add, download, or library import possible on a fresh install).

#### Scenario: Registering a root folder is validated

- **WHEN** `POST /api/v1/rootfolder` supplies a path
- **THEN** an absolute, existing, writable directory registers and is immediately listed with free space; a relative path, missing directory, unwritable directory, duplicate, or a path nested under (or containing) an existing root is rejected with a structured 400 naming the problem

#### Scenario: Removing a root folder is guarded

- **WHEN** `DELETE /api/v1/rootfolder/{id}` is called
- **THEN** an unreferenced root is removed (files on disk untouched); a root still referenced by any series is refused with a 409-class error naming the count, and an unknown id is a 404

#### Scenario: Default path is derived from the registered root and a safe template

- **WHEN** a series is added against a registered root folder with no explicit path
- **THEN** its stored path is `{root}/{safe series title} ({start_year})`, where the title component is sanitized (no path separators, reserved names, or trailing dots/spaces) from the CV title, and the series folder is created under that root

#### Scenario: Per-series path override must stay under a registered root

- **WHEN** `PUT /api/v1/series/{id}` sets a path that is not under any registered root folder
- **THEN** the request is rejected with a client error and the stored path is unchanged

#### Scenario: A valid path change renames the directory with rollback on failure

- **WHEN** a series' path is changed to a valid location under a registered root
- **THEN** the stored path is updated and the on-disk directory is moved/renamed; if the directory rename fails, the path row change is rolled back so the row and disk stay consistent
