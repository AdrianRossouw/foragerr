# opds — cbr-support deltas

## ADDED Requirements

### Requirement: FRG-OPDS-016 — RAR-backed archive access for page streaming

The archive layer serving OPDS page streaming, page counting, and cover extraction SHALL support RAR archives (CBR) via an external extraction backend (`rarfile` over an `unrar` binary, or a configured libarchive fallback), behind the same single archive-opener seam as ZIP — preserving the FRG-OPDS-008 link contract, FRG-OPDS-009 count caching, FRG-OPDS-010 natural ordering, and the existing resource limits (member-count and size ceilings, image-decode confinement, single-member streaming extraction, no full-archive extraction). Archive type SHALL be detected by content when the extension misleads (a ZIP renamed `.cbr` and the reverse SHALL open correctly). A missing or failing extraction backend SHALL degrade to the FRG-OPDS-008 non-listable behavior (download link only, stream 404) — never an error feed.

#### Scenario: CBR streams page-by-page like CBZ

- **WHEN** a PSE client requests pages of a CBR issue-file with the RAR backend available
- **THEN** the entry carries a PSE link with an accurate `pse:count`, each in-range page returns its image in natural order with a correct `image/*` content-type, and width-capped requests return downscaled images — byte-identical semantics to the CBZ path.

#### Scenario: Existing CBR rows heal lazily without re-import

- **WHEN** a CBR `issue_files` row imported before RAR support (page_count NULL) is first streamed or its feed is rendered after first stream
- **THEN** the page count is computed once, written back, and subsequent feed renders emit the PSE link with zero archive I/O.

#### Scenario: Misnamed archives open by content detection

- **WHEN** a ZIP archive renamed `.cbr` (or a RAR renamed `.cbz`) is listed or streamed
- **THEN** content detection routes it to the correct opener and it lists, counts, and streams normally.

#### Scenario: Backend absence degrades, never errors

- **WHEN** the extraction backend is missing or fails on a specific archive (e.g. encrypted RAR)
- **THEN** that entry emits the whole-file download link with no PSE link, its stream endpoint returns 404, the event is logged, and feed rendering is unaffected.

#### Scenario: RAR path enforces the same resource limits

- **WHEN** a RAR archive exceeding the member-count or member-size ceilings (or containing an image exceeding decode limits) is streamed
- **THEN** the request is refused within the same limit framework as ZIP, via single-member streaming extraction only — the archive is never fully extracted to disk.
