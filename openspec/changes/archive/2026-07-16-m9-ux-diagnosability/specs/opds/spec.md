# opds — m9-ux-diagnosability deltas

## ADDED Requirements

### Requirement: FRG-OPDS-017 — HEAD requests answered on OPDS routes

The OPDS server SHALL answer HEAD requests on its feed, file, and page routes with the same status, authentication challenge, and content type as the corresponding GET (without a body), so reader apps and proxies that preflight with HEAD do not misread the catalog as absent. Direct-file downloads additionally report the file's true Content-Length; page/cover streams do not (their length exists only after a render HEAD deliberately skips), and HEAD status parity on those routes is achieved via the same existence checks as GET (cached page count or one bounded listing — never a member read or decode).

- **Milestone**: M9 (m9-ux-diagnosability)
- **Source**: M9 finding F22 — HEAD /opds returned 404 JSON while GET served the feed.

#### Scenario: HEAD mirrors GET

- **WHEN** a client issues HEAD to the OPDS root, a feed, an acquisition file, or a page-stream URL with valid Basic credentials
- **THEN** the response status, authentication behavior, and content type match the GET equivalent, with no body (and true Content-Length on the direct-file route); an out-of-range page or unstreamable archive 404s on HEAD exactly as on GET

#### Scenario: Unauthenticated HEAD still challenges

- **WHEN** a client issues HEAD to an OPDS route without credentials
- **THEN** it receives the same 401 + `WWW-Authenticate: Basic` challenge as a GET

### Requirement: FRG-OPDS-018 — File-less series can be hidden from OPDS shelves

OPDS series listings SHALL support omitting series that have no downloadable files via configuration (`opds_hide_fileless_series`, **off by default** — the shelf mirrors the full library, wanted-but-fileless series included). When enabled, reader clients browse only shelves that contain something to read, the root feed advertises the All Series shelf only when it would be non-empty, and a series regains its entry as soon as its first file imports.

- **Milestone**: M9 (m9-ux-diagnosability)
- **Source**: M9 finding F23 — freshly added, still-empty series rendered as empty shelves on the iPad reader.
- **Notes**: Default flipped show-ward at the gate (owner amendment 2026-07-16, superseding the proposal's default-on wording). When enabled, the filter governs *browse* surfaces — the series shelf and the root feed's advertisement of it (an advertised shelf must not open empty). OPDS *search* deliberately stays unfiltered: a reader who asks for a title by name should find it even before its first file lands (the same recoverability posture as FRG-UI-032).

#### Scenario: Full library on the shelf by default

- **WHEN** the library holds a series with zero issue files and a reader requests the series feed with default configuration
- **THEN** that series renders on the shelf like any other (the shelf mirrors the library, wanted series included)

#### Scenario: Opt-in hiding

- **WHEN** the operator enables `opds_hide_fileless_series` and a reader requests the series feed
- **THEN** file-less series are absent from the feed (and the root feed advertises the All Series shelf only when it would list something), while series with files render normally; a hidden series appears as soon as its first file imports
