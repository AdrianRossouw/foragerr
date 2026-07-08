# opds Spec Delta

## MODIFIED Requirements

### Requirement: FRG-OPDS-008 — OPDS-PSE page streaming

Issue-file entries SHALL carry an OPDS-PSE 1.0 link (`rel="http://vaemendis.net/opds-pse/stream"`, namespace `http://vaemendis.net/opds-pse/ns` declared on the feed) whose `href` is a URI template with literal `{pageNumber}` and `{maxWidth}` placeholders and which advertises an accurate `pse:count`, emitted **alongside** the existing whole-file acquisition link (FRG-OPDS-005) so a non-PSE reader is unaffected. A stream endpoint SHALL return a **single page image**: the page is the archive's image members in natural order (FRG-OPDS-010) indexed by `pageNumber`; the file is resolved **by library id via the FRG-OPDS-005 path-confinement resolver** (never a client-supplied path); an out-of-range or negative `pageNumber` returns a 4xx; a `maxWidth`/`width` request returns an image **no wider than requested** (server-side downscale, aspect preserved); the response carries a correct `image/*` `Content-Type`. An entry whose archive is not listable (e.g. a CBR with no unrar support) SHALL carry **no** PSE link and its stream endpoint SHALL 404.

- **Milestone**: M3

#### Scenario: Page-by-page stream with bounds and width

- **WHEN** a PSE-capable client (or scripted equivalent) requests successive `pageNumber`s of a listable issue, and separately requests a page with a `width`
- **THEN** each in-range page returns its image with an `image/*` content-type in natural order; an out-of-range or negative page returns 4xx; the `width` response is an image no wider than requested

#### Scenario: Resolution is library-id only

- **WHEN** the stream endpoint is called
- **THEN** the file is located by `issue_file_id` through the same confinement resolver as whole-file download, and no request field is ever used as a filesystem path

#### Scenario: Non-listable archive carries no PSE link

- **WHEN** an issue's only file is an archive whose members cannot be listed (CBR without unrar support)
- **THEN** its feed entry emits the whole-file download link but no PSE stream link, and a direct stream request for it returns 404

### Requirement: FRG-OPDS-009 — Cached page counts and page index

Per-issue-file page counts (`pse:count`) SHALL be computed once and persisted on the `issue_files` row, so that **feed rendering performs zero archive I/O** (the M1 no-archive-at-render invariant is preserved) and repeated stream requests do not re-enumerate for counting. The count SHALL be populated at import from the archive open the pipeline already performs (no additional archive open); a not-yet-computed count (legacy or scan-discovered row, or an archive unlistable at import) SHALL be computed **lazily on first access and written back**. A cached count SHALL be invalidated when the underlying file changes: a re-import replaces the row, and the lazy path SHALL recompute when the stored file size no longer matches the file on disk.

- **Milestone**: M3

#### Scenario: Feed render does no archive I/O for counts

- **WHEN** a series feed carrying issue-file entries is rendered twice
- **THEN** no archive is opened for page-count purposes on either render (the count is read from the persisted column), and if import populated the count, none was opened the first time either

#### Scenario: Lazy compute and write-back for a NULL count

- **WHEN** an issue-file row has no stored page count and its page is first streamed
- **THEN** the count is computed from the archive, the page is served, and the count is written back so the next feed render reads it without opening the archive

#### Scenario: File change invalidates the count

- **WHEN** an issue-file's archive is replaced (re-import, or a size change detected on lazy read)
- **THEN** the persisted page count is refreshed to match the new file

### Requirement: FRG-OPDS-010 — Natural page ordering within archives

Pages within an archive SHALL be the members whose extension is a recognized image type (jpg/jpeg/png/webp) in **numeric-aware natural order** of member name — `2.jpg` before `10.jpg` regardless of zero-padding — excluding directories, symlink members, and non-image members (including `ComicInfo.xml`). The **same ordering** SHALL be used for computing `pse:count` and for resolving a `pageNumber` to a member, so counts and stream indexes always agree.

- **Milestone**: M3

#### Scenario: Numeric-aware order, images only

- **WHEN** an archive contains members `1.jpg`, `2.jpg`, `10.jpg`, a `sub/` directory, and a `ComicInfo.xml`
- **THEN** PSE page indexes 0,1,2 map to `1.jpg`,`2.jpg`,`10.jpg` in that order, `pse:count` is 3, and the directory and `ComicInfo.xml` neither count nor shift numbering

### Requirement: FRG-OPDS-011 — Cover and thumbnail links with local fallback

Issue-file entries SHALL emit both `http://opds-spec.org/image` and `http://opds-spec.org/image/thumbnail` links. When the issue has no stored remote ComicVine cover, the server SHALL serve a **locally generated cover** — the archive's first page (natural order) extracted, resized, and cached per issue-file in a key space distinct from the per-series ComicVine cover cache — so that no downloadable entry is cover-less and thumbnails resolve **without any client request to a third-party host**. A non-listable archive with no remote cover MAY remain cover-less (its whole-file download is unaffected).

- **Milestone**: M3

#### Scenario: Cover-less issue gets a local cover with no external egress

- **WHEN** an issue with no ComicVine image URL is viewed in an OPDS client on the tailnet with no internet route
- **THEN** the issue shows a cover extracted from its first page, and the thumbnail is served by the application, not hotlinked to a third-party CDN

### Requirement: FRG-OPDS-012 — Resource limits on archive and image handling

The archive-opening and image-scaling paths introduced for PSE and local covers SHALL enforce **configurable** resource limits: a maximum archive member count and per-page decompressed size (checked against declared central-directory sizes before decompression), an image **pixel-dimension cap enforced before the image is decoded** (decompression-bomb defense), and a **per-request time bound**. A request that would exceed any limit SHALL fail with a 4xx/5xx and a bounded log line rather than exhausting memory or CPU. The untrusted-image decode path SHALL NOT enable truncated-image loading. Extraction SHALL be gated on the archive being safe to extract, and each member name SHALL be re-checked for path-safety before it is read.

- **Milestone**: M3

#### Scenario: Zip-bomb / pixel-bomb degrades safely

- **WHEN** a crafted CBZ with an over-cap declared member size, or a member decoding to over-cap pixel dimensions, is streamed or used for a cover
- **THEN** the request fails with a bounded 4xx/5xx and a log line, the process does not exhaust memory/CPU, and the limits that triggered it are operator-configurable

#### Scenario: Member path-safety re-checked before read

- **WHEN** the stream/cover path selects an archive member to read
- **THEN** the member name is re-validated (no traversal/absolute/symlink) before any bytes are read, independent of the import-time check
