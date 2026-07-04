# OPDS — OPDS Catalog Server Specification

## Purpose

Baseline requirements for opds catalog server, mined from the
Phase 1 reference research (`docs/research/`). Baseline depth per the Phase 2 scope
decision: SHALL + coarse acceptance; scenario-level elaboration happens in the
milestone change that implements each requirement (FRG-PROC-003, FRG-PROC-009).

## Requirements

### Requirement: FRG-OPDS-001 — OPDS 1.2 Atom catalog with navigation root

The system SHALL serve an OPDS 1.2 (Atom) catalog from a single configurable base path, whose root navigation feed links to the available shelves (at minimum All Series; later Recent Additions, Publishers, Story Arcs) and only surfaces shelves that have content, with correct OPDS link types (`application/atom+xml; profile=opds-catalog; kind=navigation|acquisition`).

- **Milestone**: M1
- **Source**: mylar-opds.md §1 (profile, feed hierarchy) and §6 baseline candidate requirements.
- **Notes**: M1 shelf set = All Series only (+ Recent in M2). Mylar's single-endpoint `?cmd=` dispatch is replaced by proper per-feed routes — deliberate divergence. OPDS 2.0/JSON deliberately excluded (see final OPDS requirement).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** An OPDS client (or XML validation of the feed) pointed at the base path lists the library shelves and can navigate root → series list → series issues; empty shelves are absent from the root.

### Requirement: FRG-OPDS-002 — Acquisition feeds with per-entry metadata

Series acquisition feeds SHALL list the series' downloadable issues with per-entry title, updated timestamp (file-added or release date), author (writer) and summary where known from stored metadata, and cover + thumbnail image links — without opening archive files during feed rendering.

- **Milestone**: M1
- **Source**: mylar-opds.md §2 (metadata, covers), §5 W3 (open-every-archive anti-pattern), §6.
- **Notes**: "No archive I/O at feed time" is a hard divergence from Mylar (its `OPDS_METAINFO` + pse_count open every file per render). Metadata comes from DB fields populated at import time.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A series feed renders all owned issues with titles and timestamps; feed generation for a 200-issue series completes without any archive I/O (verifiable by instrumentation/test double).

### Requirement: FRG-OPDS-003 — Library-id-based file resolution only (no client-supplied paths)

Every OPDS download, stream, and image URL SHALL identify its target exclusively by an internal library identifier (issue-file id or issue id); the server SHALL resolve that id to a filesystem path from the database, verify the resolved path is inside a managed library root, and SHALL NOT accept any client-supplied filesystem path or filename parameter in any OPDS route.

- **Milestone**: M1
- **Source**: mylar-opds.md §5 S1 (deliverFile path traversal — "the headline finding"), §6 ("impossible by construction").
- **Notes**: Security-by-construction requirement — the traversal must be impossible to express, not merely rejected. Triggers FRG-PROC-006: STRIDE + risk register entry in the same change that adds the listener.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Route-schema review/tests confirm no OPDS endpoint has a path/file parameter; a request for a non-existent or out-of-root id returns 404; the Mylar `?cmd=deliverFile&file=/etc/passwd` attack class is unrepresentable in the API surface.

### Requirement: FRG-OPDS-004 — Parameterized queries throughout

All database queries issued by the OPDS server SHALL use parameter binding for every client-influenced value (ids, page indexes, search terms); no SQL string SHALL be built by concatenating or interpolating request input.

- **Milestone**: M1
- **Source**: mylar-opds.md §5 S3 (string-concatenated SQL in `_Comic`/`_StoryArc`), §6.
- **Notes**: Trivially satisfied by the ORM/query layer, but stated as a requirement so it gets a tagged test (FRG-PROC-004) and a risk-register line. Applies app-wide in spirit; OPDS is the surface where Mylar got it wrong.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Code review/static check of the OPDS module finds no f-string/concat SQL; a request with `comicid`-style injection payloads (`" OR 1=1 --`) in id parameters returns 404/422 and provably executes no injected SQL.

### Requirement: FRG-OPDS-005 — Whole-file download with correct comic MIME types

Each issue entry SHALL provide an acquisition link that downloads the original archive unmodified, served with the correct specific media type — `application/vnd.comicbook+zip` for CBZ and `application/vnd.comicbook-rar` for CBR — both in the feed's `link type` attribute and in the download response's Content-Type header, with a filename provided via Content-Disposition.

- **Milestone**: M1
- **Source**: mylar-opds.md §2 (octet-stream), §5 W6, §6 (specific MIME types).
- **Notes**: Divergence from Mylar's generic octet-stream. Prefer `vnd.comicbook+zip`/`comicbook-rar`; also acceptable to additionally advertise legacy `application/x-cbz`/`x-cbr` if a target client needs it — record client findings under the Panels/Chunky open question. No mark-as-read side effect on download (Mylar's `_Issue` marks read; reading state is not OPDS's job here).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Downloading a CBZ and a CBR yields byte-identical files whose feed link type and response Content-Type match the container format; neither is served as `application/octet-stream`.

### Requirement: FRG-OPDS-006 — Feed pagination with totals

All feeds that can exceed a configurable page size SHALL paginate with Atom `next`/`previous` links plus `first`/`last` links and OpenSearch `totalResults`/`itemsPerPage`/`startIndex` elements, with every pagination link pointing back at the same feed it paginates.

- **Milestone**: M1
- **Source**: mylar-opds.md §1 (pagination), §5 W2 (copy-paste next/prev bugs), W4 (no totals), §6.
- **Notes**: The wrong-feed pagination-link bug class gets an explicit test because Mylar shipped it twice.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A shelf with more entries than the page size pages correctly through all entries; totalResults matches the true count; next/prev links resolve to the same feed type (regression test for Mylar's wrong-cmd links).

### Requirement: FRG-OPDS-007 — Working OpenSearch (or none)

The catalog SHALL either (a) advertise an OpenSearch description link, serve a valid `application/opensearchdescription+xml` document, and implement the referenced search feed returning matching series/issues, or (b) advertise no search link at all; an advertised-but-unimplemented search is prohibited.

- **Milestone**: M2
- **Source**: mylar-opds.md §4/§5 W1 (search advertised but not implemented, no descriptor), §6.
- **Notes**: Target is (a) implemented search by M2; M1 ships option (b) — omit the link. The requirement is phrased so either state is spec-compliant and Mylar's broken middle state is not.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** If the search link is present, following descriptor → templated query returns a valid acquisition/navigation feed of matches; if absent, no search link or namespace promise appears in the root.

### Requirement: FRG-OPDS-008 — OPDS-PSE page streaming

Issue entries SHALL carry an OPDS-PSE 1.0 link (`rel="http://vaemendis.net/opds-pse/stream"`, namespace `http://vaemendis.net/opds-pse/ns`) with `{pageNumber}`/`{maxWidth}` URI template placeholders and an accurate `pse:count`, and the stream endpoint SHALL return the requested single page image (bounds-checked, resolved via library id per the resolution requirement) with optional server-side downscaling to `maxWidth` and a correct image Content-Type.

- **Milestone**: M2
- **Source**: mylar-opds.md §2(b) (`_Stream`, PSE template, scale_image), §6.
- **Notes**: M1 relies on whole-file download (sufficient for iPad reading over Tailscale); PSE is the M2 streaming upgrade. Whether Panels/Chunky prefer PSE vs whole-file is an OPEN QUESTION (below) — do not reorder milestones without answering it.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A PSE-capable client (or scripted equivalent) streams an issue page-by-page; out-of-range page numbers return 4xx; `width` requests return an image no wider than requested.

### Requirement: FRG-OPDS-009 — Cached page counts and page index

Per-issue page counts (`pse:count`) and page listings SHALL be computed once (at import or first access) and persisted/cached, so that neither feed rendering nor repeated stream requests re-enumerate archive contents; cache entries SHALL invalidate when the underlying file changes.

- **Milestone**: M2
- **Source**: mylar-opds.md §5 W3, §6 ("compute pse:count lazily/cached, not by opening every archive on every feed render").
- **Notes**: Pairs with PSE; import pipeline (IMP area) is the natural producer of page counts — dedup hint for the orchestrator.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Rendering a series feed twice performs zero archive opens the second time (and none for count purposes the first time if import populated it); replacing a file updates its count.

### Requirement: FRG-OPDS-010 — Natural page ordering within archives

Pages within an archive SHALL be served in natural (numeric-aware) order of member names — `2.jpg` before `10.jpg` regardless of zero-padding — considering only recognized image members (jpg/jpeg/png/webp) and ignoring directories and non-image files.

- **Milestone**: M2
- **Source**: mylar-opds.md §2 (sorted namelist), §5 W5 (naive lexical sort), §6.
- **Notes**: Ships with PSE (page order is invisible to whole-file download). Same natural-sort must be used for page-count computation so counts and indexes agree.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** An archive with members `1.jpg, 2.jpg, 10.jpg` streams in that order via PSE page indexes 0..2; a ComicInfo.xml member does not shift page numbering.

### Requirement: FRG-OPDS-011 — Cover and thumbnail links with local fallback

Issue entries SHALL emit both `http://opds-spec.org/image` and `.../image/thumbnail` links; when no stored remote cover URL exists, the server SHALL fall back to a locally generated cover (first page extracted at import time, resized, cached) so that no downloadable entry is cover-less, and thumbnail URLs SHALL resolve without requiring client access to third-party hosts.

- **Milestone**: M2
- **Source**: mylar-opds.md §2 (covers reuse remote CV URLs; one-offs cover-less; `extract_image` exists but unused), §5/§6.
- **Notes**: Divergence from Mylar (hotlinked CV URLs). Serving covers locally also stops leaking client requests to ComicVine's CDN. Cover extraction/caching may share the IMP-area cover cache.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** An issue with no ComicVine image URL still shows a cover in an OPDS client on the tailnet with no internet egress; thumbnails are served from the application, not hotlinked.

### Requirement: FRG-OPDS-012 — Resource limits on archive and image handling

OPDS archive-opening and image-scaling operations SHALL enforce configurable resource limits — maximum archive member count and per-page decompressed size, image pixel-dimension caps before PIL decode, and per-request time bounds — rejecting requests that exceed them with a 4xx/5xx rather than exhausting memory/CPU.

- **Milestone**: M2
- **Source**: mylar-opds.md §5 S5 (zip-bomb/decompression exposure, `LOAD_TRUNCATED_IMAGES`), §6 resource limits.
- **Notes**: Untrusted-parser attack surface → FRG-PROC-006 security docs update required in the implementing change. Applies wherever archives are opened (shared with IMP) — orchestrator may hoist to a cross-area requirement.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A crafted zip-bomb CBZ in the library causes a bounded, logged failure on stream/cover requests, not process memory exhaustion; limits are configurable.

### Requirement: FRG-OPDS-013 — Recent Additions shelf

The catalog SHALL provide a Recent Additions acquisition feed of the most recently imported issues (configurable window/count), ordered newest first, paginated per the pagination requirement.

- **Milestone**: M2
- **Source**: mylar-opds.md §1 (`_Recent` shelf), §6 baseline.
- **Notes**: The highest-value shelf for the actual use case (pick up this week's haul on the iPad).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Importing a new issue places it at the top of the Recent feed; ordering is by import time, not release date.

### Requirement: FRG-OPDS-014 — Publisher browse shelf

The catalog SHALL provide a Publishers navigation feed grouping series by publisher, each publisher linking to its series, paginated per the pagination requirement.

- **Milestone**: B
- **Source**: mylar-opds.md §1 (`_Publishers`/`_Publisher`), §6.
- **Notes**: Low value for a personal library browsable by series; kept for Mylar parity. Story-arc / reading-list shelves are deliberately NOT drafted here — they belong to the ARC area's milestone and should be added to OPDS when arcs exist (dedup hint).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Series with a shared publisher appear under one publisher entry whose feed lists exactly those series.

### Requirement: FRG-OPDS-015 — Single OPDS version; no OPDS 2.0

The catalog SHALL target OPDS 1.2 only; OPDS 2.0 (JSON) support SHALL NOT be implemented unless a verified target client (Panels/Chunky on iPad) is shown to require or materially benefit from it.

- **Milestone**: B
- **Source**: mylar-opds.md §6 ("Consider offering OPDS 2.0... only if a target iPad reader benefits — flagged as optional/uncertain").
- **Notes**: OPEN QUESTION (blocking PSE priority and this requirement): verify against current Panels and Chunky documentation/testing (i) OPDS 1.2 + PSE support status, (ii) whole-file vs PSE preference, (iii) any OPDS 2.0 requirement, (iv) MIME-type handling of `vnd.comicbook+zip` vs `x-cbz`. The reference code cannot answer this (mylar-opds.md §4); schedule a small research task before the M2 OPDS change is proposed.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** No `application/opds+json` routes exist; the decision record links the client-verification outcome.

