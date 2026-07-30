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
duplicate/nesting guards still apply. The read-only flag SHALL be a
persisted property of the root, additive to the schema.

For every series whose root is read-only, and for every path that resolves
at or under a read-only root, the system SHALL refuse **fail-closed** every
disk-write path in a **checkable, enumerated set**:

1. library-import rename/move and any other import placement into the root;
2. per-series rescan file moves;
3. download-into-root (and the acquisition surface FRG-SER-022 governs);
4. delete and recycle of the root's own files;
5. post-placement archive rewrites — ComicInfo tagging and CBR→CBZ
   conversion — including the on-demand convert commands;
6. **disposal into a configured recycle-bin or duplicate-dump directory that
   resolves inside a read-only root**, whether or not the series being
   disposed of is itself read-only;

plus the source direction of (1): a move-mode import whose candidate file
resolves inside a read-only root, which would take the operator's original
out of it.

Each refusal SHALL be enforced in the flow body rather than only at the API
route, so an operation reached by enqueuing its command directly is refused
identically, and the enumeration SHALL itself be asserted by test so a new
disk-write path cannot ship outside the set. No coverage is claimed for a
disk-write path outside the enumerated set.

- **Milestone**: B (read-only-library).
- **Source**: rig finding #4 (a real, read-only-mounted collection was
  refused because roots must be writable); relates to FRG-SER-008.
- **Notes**: The feature exists to protect the operator's real files, so
  read-only is a write *boundary*, not a hint — the tests assert no write
  occurs under a read-only root across every path in the enumerated set,
  and assert the set's completeness against the command registry
  (FRG-PROC-006). The claim is deliberately bounded rather than universal:
  the boundary is only as wide as the paths it is checked at, and item 6
  was found by review AFTER the first cut shipped with items 1-5.

#### Scenario: Registering a read-only root validates readability, not writability

- **WHEN** a root is registered read-only pointing at an existing readable
  directory that is not writable
- **THEN** it registers successfully (the W_OK check is waived), while a
  missing/unreadable path, a duplicate, or a nested path is still refused
  with a structured 400

#### Scenario: Every enumerated write path is refused for a read-only root

- **WHEN** any operation in the enumerated write set is attempted against a
  read-only root — an import rename/move, a rescan move, a download into
  it, a delete/recycle, a post-placement archive rewrite, or a move-mode
  import out of it — by any route, including enqueuing its command directly
- **THEN** it is refused fail-closed with a clear reason and no bytes under
  the read-only root are created, moved, rewritten, or removed

#### Scenario: A disposal directory inside a read-only root is refused

- **WHEN** the configured recycle bin or duplicate-dump directory resolves
  inside a read-only root — whether it was submitted through the config
  API, configured before the root was registered read-only, or supplied
  through the environment or the config file
- **THEN** submitting it through the config API is rejected against its own
  field, every disposal that would move a file into it is refused at the
  point of use with a reason naming the setting, the retention prune never
  removes anything inside the read-only root, and the misconfiguration is
  reported on the health surface

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
