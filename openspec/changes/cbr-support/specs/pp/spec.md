# pp — cbr-support deltas

## MODIFIED Requirements

### Requirement: FRG-PP-018 — CBR-to-CBZ conversion and library-wide retagging

The system SHALL optionally convert CBR archives to CBZ at import time as an explicit, off-by-default library policy surfaced with the format-preference configuration — verifying the converted archive (member count matches; final member decodes) before the original is discarded, recording the conversion as a history event, and updating the `issue_files` row (path, size, page count) atomically with the swap. On-demand conversion SHALL be available per issue and per series. Library-wide retagging (ComicInfo re-write across existing archives) remains out of scope until the META tagging dependency lands and is explicitly deferred.

- **Milestone**: 0.9.x (pulled from B; adopted by cbr-support)
- **Source**: MFS §4 Metadata tagging (CBR→CBZ, CBR2CBZ_ONLY, group_metatag with CV batch-limit protection); MFS capability map META/PP.
- **Notes**: Conversion is where the cbz-preferred format profile (quality AREA) becomes actionable for existing files. Rar extraction ships via the FRG-OPDS-016 backend (`unrar` in the Docker image — deployment note). Off by default per the FRG-PP-020 non-destructive stance. The retag half of the original requirement follows META, not this change.

#### Scenario: Opt-in conversion verifies before discarding

- **WHEN** the conversion policy is enabled and a CBR imports
- **THEN** the produced CBZ is verified (member count matches the source listing; final member decodes as an image) before the original file is removed, the `issue_files` row swaps to the CBZ path/size/page-count atomically, and a conversion history event is recorded.

#### Scenario: Off by default — no conversion without opt-in

- **WHEN** a CBR imports with default configuration
- **THEN** the file imports as-is (`.cbr`, byte-identical) and no conversion occurs.

#### Scenario: Failed verification keeps the original

- **WHEN** conversion output fails verification (truncated write, undecodable member)
- **THEN** the original CBR is kept untouched as the imported file, the failure is logged as a history event, and the import itself still succeeds.

#### Scenario: On-demand conversion per issue and per series

- **WHEN** an operator triggers conversion for one issue or one series with the backend available
- **THEN** each targeted CBR converts under the same verify-before-discard semantics, and already-CBZ files are skipped as no-ops.
