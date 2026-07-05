## MODIFIED Requirements

### Requirement: FRG-OPDS-001 — OPDS 1.2 Atom catalog with navigation root

The system SHALL serve an OPDS 1.2 (Atom) catalog from a single configurable base path, whose root navigation feed links to the available shelves (at minimum All Series; later Recent Additions, Publishers, Story Arcs) and only surfaces shelves that have content, with correct OPDS link types (`application/atom+xml; profile=opds-catalog; kind=navigation|acquisition`).

- **Milestone**: M1
- **Source**: mylar-opds.md §1 (profile, feed hierarchy) and §6 baseline candidate requirements.
- **Notes**: M1 shelf set = All Series only (+ Recent in M2). Mylar's single-endpoint `?cmd=` dispatch is replaced by proper per-feed routes — deliberate divergence. OPDS 2.0/JSON deliberately excluded (see final OPDS requirement).

#### Scenario: Root navigation feed lists only non-empty shelves

- **WHEN** a client GETs the configured base path (default `/opds`) against a library that has at least one series
- **THEN** the response is a valid OPDS 1.2 Atom navigation feed whose only shelf entry is All Series, linked with `type="application/atom+xml; profile=opds-catalog; kind=navigation"`, and no empty shelf (Recent/Publishers/Story Arcs) appears in M1

#### Scenario: Per-feed routes replace cmd dispatch

- **WHEN** a client navigates root → `/opds/series` → `/opds/series/{id}`
- **THEN** each route returns its own feed (All Series navigation list, then that series' acquisition feed) and no `?cmd=` dispatch parameter exists anywhere in the OPDS URL surface

#### Scenario: Base path is configurable

- **WHEN** the OPDS base path is configured to a non-default value and a client GETs that path
- **THEN** the root feed is served there, all in-feed links are relative to the configured base, and the default `/opds` path is not served

#### Scenario: Acquisition shelf carries the acquisition kind

- **WHEN** the All Series shelf resolves to a feed of downloadable issues
- **THEN** the link to that acquisition feed carries `type="application/atom+xml; profile=opds-catalog; kind=acquisition"`, distinct from the navigation kind used for browse feeds

### Requirement: FRG-OPDS-002 — Acquisition feeds with per-entry metadata

Series acquisition feeds SHALL list the series' downloadable issues with per-entry title, updated timestamp (file-added or release date), author (writer) and summary where known from stored metadata, and cover + thumbnail image links — without opening archive files during feed rendering.

- **Milestone**: M1
- **Source**: mylar-opds.md §2 (metadata, covers), §5 W3 (open-every-archive anti-pattern), §6.
- **Notes**: "No archive I/O at feed time" is a hard divergence from Mylar (its `OPDS_METAINFO` + pse_count open every file per render). Metadata comes from DB fields populated at import time.

#### Scenario: Entries render from DB fields

- **WHEN** a client GETs a series acquisition feed for a series with owned issues
- **THEN** each entry carries a title, an `updated` timestamp (file-added, falling back to release date), and author/summary where those DB fields are populated, all sourced from database rows rather than archive contents

#### Scenario: Zero archive I/O at feed render

- **WHEN** a 200-issue series feed is rendered with archive-open operations instrumented by a test double
- **THEN** the feed completes successfully and the instrumentation records zero archive opens during the request

#### Scenario: Cover and thumbnail links point at the local cache

- **WHEN** an entry advertises cover and thumbnail image links
- **THEN** the link URLs address the application's local cover-cache endpoint and no ComicVine/remote host URL appears in the feed

### Requirement: FRG-OPDS-003 — Library-id-based file resolution only (no client-supplied paths)

Every OPDS download, stream, and image URL SHALL identify its target exclusively by an internal library identifier (issue-file id or issue id); the server SHALL resolve that id to a filesystem path from the database, verify the resolved path is inside a managed library root, and SHALL NOT accept any client-supplied filesystem path or filename parameter in any OPDS route.

- **Milestone**: M1
- **Source**: mylar-opds.md §5 S1 (deliverFile path traversal — "the headline finding"), §6 ("impossible by construction").
- **Notes**: Security-by-construction requirement — the traversal must be impossible to express, not merely rejected. Triggers FRG-PROC-006: STRIDE + risk register entry in the same change that adds the listener.

#### Scenario: Download route takes only an issue-file id

- **WHEN** the route table for OPDS is inspected
- **THEN** the only download route is `/opds/file/{issue_file_id}` whose sole parameter is an integer id, and no OPDS route declares a path, file, or filename parameter

#### Scenario: id resolves through DB then containment check

- **WHEN** a client requests `/opds/file/{issue_file_id}` for a valid id
- **THEN** the server looks up `issue_files.path` for that id, runs a safe_join containment check against a managed library root, and returns a `FileResponse` only when the resolved path is inside the root

#### Scenario: Unknown or foreign id returns 404

- **WHEN** a client requests a file id that does not exist or resolves outside any managed library root
- **THEN** the response is 404 and no file bytes are served

#### Scenario: deliverFile attack class is unrepresentable

- **WHEN** a client attempts the Mylar `?cmd=deliverFile&file=/etc/passwd` attack against the OPDS surface
- **THEN** there is no route or parameter that accepts the path, so the request cannot be expressed against the API and no arbitrary file is read

### Requirement: FRG-OPDS-004 — Parameterized queries throughout

All database queries issued by the OPDS server SHALL use parameter binding for every client-influenced value (ids, page indexes, search terms); no SQL string SHALL be built by concatenating or interpolating request input.

- **Milestone**: M1
- **Source**: mylar-opds.md §5 S3 (string-concatenated SQL in `_Comic`/`_StoryArc`), §6.
- **Notes**: Trivially satisfied by the ORM/query layer, but stated as a requirement so it gets a tagged test (FRG-PROC-004) and a risk-register line. Applies app-wide in spirit; OPDS is the surface where Mylar got it wrong.

#### Scenario: Static check finds no interpolated SQL

- **WHEN** a static test scans the OPDS module's source
- **THEN** it finds no f-string, `%`, `.format`, or `+` concatenation building SQL text from request input; every query passes client-influenced values as SQLAlchemy bound parameters

#### Scenario: Injection payload in an id parameter is inert

- **WHEN** a client sends a `" OR 1=1 --`-style payload in an id or page parameter
- **THEN** the request returns a 404/422 (type-validation or not-found), executes no injected SQL, and does not leak additional rows

### Requirement: FRG-OPDS-005 — Whole-file download with correct comic MIME types

Each issue entry SHALL provide an acquisition link that downloads the original archive unmodified, served with the correct specific media type — `application/vnd.comicbook+zip` for CBZ and `application/vnd.comicbook-rar` for CBR — both in the feed's `link type` attribute and in the download response's Content-Type header, with a filename provided via Content-Disposition.

- **Milestone**: M1
- **Source**: mylar-opds.md §2 (octet-stream), §5 W6, §6 (specific MIME types).
- **Notes**: Divergence from Mylar's generic octet-stream. Prefer `vnd.comicbook+zip`/`comicbook-rar`; also acceptable to additionally advertise legacy `application/x-cbz`/`x-cbr` if a target client needs it — record client findings under the Panels/Chunky open question. No mark-as-read side effect on download (Mylar's `_Issue` marks read; reading state is not OPDS's job here).

#### Scenario: CBZ download carries the zip comic MIME type

- **WHEN** a client downloads a CBZ issue via its acquisition link
- **THEN** the feed link `type` and the response `Content-Type` are both `application/vnd.comicbook+zip`, the response carries a `Content-Disposition` filename, and the bytes are byte-identical to the stored archive

#### Scenario: CBR download carries the rar comic MIME type

- **WHEN** a client downloads a CBR issue via its acquisition link
- **THEN** the feed link `type` and the response `Content-Type` are both `application/vnd.comicbook-rar` and the bytes are byte-identical to the stored archive

#### Scenario: Never served as octet-stream, no read side effect

- **WHEN** any issue (cbz, cbr, or pdf) is downloaded
- **THEN** the Content-Type is the format-specific type (pdf → `application/pdf`), never `application/octet-stream`, and no reading/mark-as-read state is mutated by the download

### Requirement: FRG-OPDS-006 — Feed pagination with totals

All feeds that can exceed a configurable page size SHALL paginate with Atom `next`/`previous` links plus `first`/`last` links and OpenSearch `totalResults`/`itemsPerPage`/`startIndex` elements, with every pagination link pointing back at the same feed it paginates.

- **Milestone**: M1
- **Source**: mylar-opds.md §1 (pagination), §5 W2 (copy-paste next/prev bugs), W4 (no totals), §6.
- **Notes**: The wrong-feed pagination-link bug class gets an explicit test because Mylar shipped it twice.

#### Scenario: Multi-page shelf paginates through all entries with totals

- **WHEN** a client pages through a shelf that has more entries than the configured page size using `?page=`
- **THEN** every entry is reachable across the pages, `opensearch:totalResults` equals the true count, and `itemsPerPage`/`startIndex` reflect the page size and current offset

#### Scenario: Pagination links target the same feed (Mylar wrong-cmd regression)

- **WHEN** a paginated feed emits `next`, `previous`, `first`, and `last` links
- **THEN** every one of those links resolves back to the same feed route it paginates (not a different feed), and following them lands on the expected page

#### Scenario: Per-page cap is enforced

- **WHEN** a client requests a page size above the configured per-page cap
- **THEN** the server clamps to the cap (or rejects with a 4xx) rather than returning an unbounded page
