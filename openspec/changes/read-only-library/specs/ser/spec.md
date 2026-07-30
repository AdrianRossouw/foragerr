# ser — delta for read-only-library

## MODIFIED Requirements

### Requirement: FRG-SER-008 — Root folders and series paths

The system SHALL support one or more configured root folders, manageable through the API — registration (`POST /rootfolder`, validated) and removal (`DELETE /rootfolder/{id}`, refused while series reference it) — each series SHALL have a path defaulting to `<root folder>/<templated series folder>` created on add, with the folder-name template configurable and the path overridable per series. A root folder MAY additionally be registered **read-only** (FRG-SER-021): its registration requirement becomes readable-OR-writable rather than writable-only, and every series whose root is read-only is subject to the write-refusal boundary FRG-SER-021/FRG-SER-022 define, in place of the ordinary writable-root write behavior.

- **Milestone**: M1; read-only extension B (read-only-library).
- **Source**: sonarr-architecture.md §1.2 step 1, §5.5 (RootFolderService); mylar-feature-surface.md capability map SER (multiple destination dirs, create-folders-on-add, per-series location); read-only extension: rig finding #4 (a real read-only-mounted collection was refused because every root previously had to be writable).
- **Notes**: Subsumes Mylar's `MULTIPLE_DEST_DIRS` and per-series location + dir lock. Folder *naming* token engine is owned by the import/rename area; SER owns the association. Management endpoints added in m2-daily-surfaces: registration was previously unreachable outside direct DB seeding (a first-run blocker found in live testing — no series add, download, or library import possible on a fresh install). Read-only extension: the writable-directory check is a discriminated OR, not a relaxation — an ordinary root is still refused if unwritable, and a read-only root is still refused if unreadable; nothing in between is accepted.

#### Scenario: Registering a root folder is validated

- **WHEN** `POST /api/v1/rootfolder` supplies a path
- **THEN** an absolute, existing directory registers and is immediately listed with free space, provided it is writable, or — when registered with the read-only flag — readable; a relative path, a missing directory, a directory that fails the applicable writable-or-readable check for how it was registered, a duplicate, or a path nested under (or containing) an existing root is rejected with a structured 400 naming the problem

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

## ADDED Requirements

### Requirement: FRG-SER-021 — Read-only library root

The system SHALL allow a library root to be registered **read-only**. A
read-only root's registration SHALL validate the path as an absolute,
existing, **readable** directory (the writable-directory requirement of
FRG-SER-008 is waived for it, replaced by readability), while the
duplicate/nesting guards still apply. For every series whose root is
read-only, all disk-write paths — library-import rename/move, per-series
rescan file moves, download-into-root, and delete/recycle-bin — SHALL be
refused **fail-closed**, so foragerr never writes to a read-only root
even if a caller reaches a write path by another route. The read-only
flag SHALL be a persisted property of the root, additive to the schema.

- **Milestone**: B (read-only-library).
- **Source**: rig finding #4 (a real, read-only-mounted collection was
  refused because roots must be writable); relates to FRG-SER-008.
- **Notes**: The feature exists to protect the operator's real files, so
  read-only is a write *boundary*, not a hint — the tests assert no write
  occurs under a read-only root across every path (FRG-PROC-006).

#### Scenario: Registering a read-only root validates readability, not writability

- **WHEN** a root is registered read-only pointing at an existing readable
  directory that is not writable
- **THEN** it registers successfully (the W_OK check is waived), while a
  missing/unreadable path, a duplicate, or a nested path is still refused
  with a structured 400

#### Scenario: Every write path is refused for a read-only root

- **WHEN** any operation that would write under a read-only root is
  attempted — an import rename/move, a rescan move, a download into it, or
  a delete/recycle — by any route
- **THEN** it is refused fail-closed with a clear reason and no bytes are
  written to the read-only root

### Requirement: FRG-SER-022 — Read-only series are browse/serve-only

A series whose root is read-only SHALL be **browse and serve only**: it is
never monitored, wanted, searched, or acquired, and its files are never
moved or deleted. It SHALL still refresh ComicVine metadata (written to
the database, not the root) and cache covers (to the config directory, not
the root), and it SHALL serve over OPDS exactly like any other series. Any
attempt to monitor, mark wanted, search, grab, or delete-files for such a
series SHALL be refused with a clear reason rather than silently no-op.

- **Milestone**: B (read-only-library).
- **Source**: rig finding #4; the browse-only shape agreed with the owner
  2026-07-29 (no acquisition into a read-only library).
- **Notes**: A read-only series has nowhere to download into, so the
  acquisition surface (monitoring, wanted, search, grab) is off by
  construction — the value is reading an existing collection, served to
  the reader.

#### Scenario: A read-only series serves but does not acquire

- **WHEN** a series on a read-only root is inspected
- **THEN** it renders and serves over OPDS with its existing files, its
  metadata refreshes normally, and it exposes no monitored/wanted state
  and no search — and a direct monitor/search/grab call for it is refused
  with a clear reason

#### Scenario: Metadata and covers write off the read-only root

- **WHEN** a read-only series refreshes metadata and caches a cover
- **THEN** the metadata is written to the database and the cover to the
  config directory — never to the read-only root
