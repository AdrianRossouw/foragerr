## MODIFIED Requirements

### Requirement: FRG-SEC-003 — Archive-processing safety (bomb / zip-slip limits)

Every operation that opens, decompresses, extracts, or rewrites a comic archive (import-time validity/image checks, cover/first-page extraction, OPDS page streaming, pack extraction, and in-process ComicInfo.xml tagging) SHALL enforce configurable limits — maximum member count, maximum per-member and total decompressed size, and image pixel-dimension caps before decode — and SHALL reject any archive member whose name contains a path-separator escape, absolute path, or symlink/hardlink, writing extracted or rewritten content only inside a confined staging or target directory.

- **Milestone**: M1
- **Source**: mylar-opds.md §5 S5 + mylar-ddl.md §4 (extraction/bomb concerns drafts scope to OPDS and DDL packs only). Gap G-4; RISK-010, RISK-008 (non-DDL paths), RISK-005 (import/cover image decode).
- **Notes**: Consolidates the hoist hints in FRG-OPDS resource limits and the pack-scoped FRG-DDL safe extraction. FRG-PP archive validity checks structure but states no bomb caps; cover extraction and tagging write by member name (zip-slip). One shared archive-safety utility serves IMP, PP, OPDS, and DDL.

#### Scenario: All archive callers go through the single shared archive-safety utility

- **WHEN** any archive-touching path (import validity/image check, cover/first-page extraction, OPDS page streaming, pack extraction, ComicInfo.xml tagging) opens or rewrites an archive
- **THEN** it does so through the one shared `security/archives.py` utility that enforces the member-count cap, per-member and total decompressed-size caps, and nesting depth of 0, with those limits configurable

#### Scenario: The committed hostile corpus is rejected as typed failures without extraction or exhaustion

- **WHEN** each artifact of the committed hostile corpus — zip bomb, nested bomb, zip-slip member name, symlink member, oversized member, and password-protected archive — is fed to the shared utility
- **THEN** every one is rejected as a typed, bounded, logged failure with no extraction, no crash, and no memory/CPU exhaustion

#### Scenario: Escaping and symlink member names are rejected before any write

- **WHEN** an archive contains a member whose name is absolute, contains a `../`/separator-escape, or is a symlink/hardlink entry
- **THEN** the member is rejected before decompression and no file is ever written outside the confined staging or target directory

### Requirement: FRG-SEC-004 — Filesystem path confinement (safe-join)

Every filesystem path the system constructs from external or derived input — series/issue destination folders and filenames (from ComicVine-derived titles), cover-cache file paths, manual-import target paths, and download-client-reported paths after remote mapping — SHALL be produced through a single safe-join utility that normalizes the result and guarantees it remains within the configured managed root (library root, `/config` cache, or download staging), refusing any input that would escape confinement.

- **Milestone**: M1
- **Source**: STRIDE analysis (only FRG-OPDS library-id resolution and FRG-DDL safe filename generation have explicit confinement; rename/move/cover paths rely on illegal-char policy without a central containment guarantee). Gap G-4a; RISK-019, RISK-029.
- **Notes**: Complements FRG-META untrusted-input sanitization and FRG-PP token renaming / safe file operations by adding the containment invariant they assume but do not state. Pairs with FRG-SEC-003.

#### Scenario: safe_join is the only path constructor for pipeline and renamer destinations

- **WHEN** the import pipeline or the renamer constructs a destination folder or filename from ComicVine-derived titles or client-reported (remote-mapped) paths
- **THEN** the path is produced solely through the single `security/paths.py` `safe_join(root, *parts)` utility, which normalizes the result and verifies via realpath that it is contained under the configured managed root before any write

#### Scenario: Traversal corpus is refused or sanitized inside the root, never escaping

- **WHEN** the property-test traversal corpus — `../` sequences, absolute paths, drive-letter prefixes, reserved device names, trailing dots/spaces, and unicode homoglyph separators — is passed as path parts
- **THEN** each input either yields a sanitized path that realpath-confirms inside the managed root or is refused with a reason, and in no case is a path produced that escapes confinement

#### Scenario: Confinement holds across import, rename/move, and cover-cache writes

- **WHEN** a ComicVine series title containing `../`, an absolute path, or a reserved/device name flows into an import, a rename/move, or a cover-cache write
- **THEN** the operation resolves to a path inside the appropriate managed root (library root, `/config` cache, or download staging) or is rejected-with-reason, never writing outside the root

#### Scenario: change-3's safe_path_component is owned solely by the safe-join utility

- **WHEN** any caller needs to sanitize an individual path component previously covered by change-3's `safe_path_component`
- **THEN** that logic is relocated into `security/paths.py` under single ownership, with no second independent copy of component sanitization elsewhere in the codebase
