# ser — delta for read-only-library

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
