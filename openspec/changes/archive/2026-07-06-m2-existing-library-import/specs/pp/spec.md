# pp — delta for m2-existing-library-import

## MODIFIED Requirements

### Requirement: FRG-PP-014 — Duplicate constraint handling

When an incoming file targets an issue that already has a file and the release is not a profile-driven upgrade, the system SHALL resolve the duplicate by a configurable constraint — preferred format or larger file size (default) — with explicit fixed-release markers (`(f1)`/`(f2)`-style) always winning, and SHALL optionally move the losing file to a duplicate-dump folder (dated subfolders supported) instead of deleting it.

- **Milestone**: M2
- **Source**: MFS §4 Duplicate handling (`duplicate_filecheck`, DUPECONSTRAINT, DDUMP); SA §5.2 (UpgradeSpecification interplay).
- **Notes**: Ordering with the profile system: profile-order upgrade decision first (Sonarr semantics); the dupe constraint only arbitrates same-rung ties — a deliberate merge of Mylar's standalone dupe logic into the Sonarr decision shape. Implementation seam: the upgrade spec's strict `new_rank > old_rank` keeps rejecting downgrades; the constraint decides only `new_rank == old_rank`. Fixed-release markers are parsed as filename annotations (parser extension). The dump folder is its own root with dated subfolders — deliberately NOT marked as a recycle bin, so recycle-bin retention pruning never touches it.

#### Scenario: Profile order still decides first; constraint only breaks ties

- **WHEN** an incoming file for an issue with an existing file ranks higher on the format-profile ladder
- **THEN** it imports as an upgrade exactly as before this change; when it ranks LOWER it is rejected as before; only an equal rung invokes the duplicate constraint

#### Scenario: Same-rung tie resolved by the configured constraint

- **WHEN** an incoming same-rung file collides under constraint `larger-size` (default) or `preferred-format`
- **THEN** under `larger-size` the bigger file wins (the incoming file is rejected if not bigger); under `preferred-format` the configured format preference decides; the outcome and reason are recorded in import history

#### Scenario: Fixed-release markers always win

- **WHEN** either the incoming or existing file carries a fixed-release marker (`(f1)`, `(f2)`, ...) and the two differ
- **THEN** the higher fix revision wins regardless of size or format constraint (an unfixed file never beats a fixed one), and equal markers fall back to the configured constraint

#### Scenario: Losing file goes to the dump folder when enabled

- **WHEN** a duplicate resolution replaces the existing file and a duplicate-dump folder is configured
- **THEN** the loser moves into a dated subfolder of the dump root (collision-suffixed, never overwritten) instead of deletion/recycle; with no dump folder configured the existing replaced-file path (recycle bin or delete) applies unchanged; recycle-bin retention pruning never deletes anything under the dump root
