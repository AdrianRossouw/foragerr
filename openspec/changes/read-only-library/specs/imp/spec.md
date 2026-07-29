# imp — delta for read-only-library

## ADDED Requirements

### Requirement: FRG-IMP-028 — Index-in-place import for read-only roots

The system SHALL, when importing a Library Import group under a
**read-only** root (FRG-SER-021), register the series and its
`issue_files` pointing at the files' **existing on-disk paths** and
perform **no rename, move, or copy** — the disk is never mutated. Matching to ComicVine, metadata population, and
cover caching proceed as for a normal import (all writing to the database
/ config directory, never the root). The resulting series is a read-only,
browse-only series (FRG-SER-022). The atomicity rule (FRG-IMP-027) is moot
for a read-only root because it makes no on-disk changes to roll back;
a group that cannot be indexed records its reason on the staging row and
creates no series.

- **Milestone**: B (read-only-library).
- **Source**: rig finding #4; index-without-mutation is the whole point of
  a read-only library.
- **Notes**: Reuses the existing scan → match → register machinery; the
  only change is that the placement step is a no-op (files stay where they
  are) and `issue_files` record the real paths. No naming template is
  applied.

#### Scenario: Indexing a read-only group leaves the files untouched

- **WHEN** a group under a read-only root is imported
- **THEN** its series and `issue_files` are registered pointing at the
  existing file paths, no file is renamed/moved/copied, and OPDS serves
  those files in place

#### Scenario: A read-only import writes only to the database and config dir

- **WHEN** a read-only group imports and its series metadata + covers are
  populated
- **THEN** the only writes are to the database and the config directory —
  the read-only root is never written to
