# opds — m9-ux-diagnosability deltas

## ADDED Requirements

### Requirement: FRG-OPDS-017 — HEAD requests answered on OPDS routes

The OPDS server SHALL answer HEAD requests on its feed, file, and page routes with the same status, authentication challenge, and headers as the corresponding GET (without a body), so reader apps and proxies that preflight with HEAD do not misread the catalog as absent.

- **Milestone**: M9 (m9-ux-diagnosability)
- **Source**: M9 finding F22 — HEAD /opds returned 404 JSON while GET served the feed.

#### Scenario: HEAD mirrors GET

- **WHEN** a client issues HEAD to the OPDS root, a feed, an acquisition file, or a page-stream URL with valid Basic credentials
- **THEN** the response status and content headers match the GET equivalent, with no body

#### Scenario: Unauthenticated HEAD still challenges

- **WHEN** a client issues HEAD to an OPDS route without credentials
- **THEN** it receives the same 401 + `WWW-Authenticate: Basic` challenge as a GET

### Requirement: FRG-OPDS-018 — File-less series omitted from OPDS shelves

OPDS series listings SHALL omit series that have no downloadable files (a behavior that is on by default and can be disabled by configuration), so reader clients browse only shelves that contain something to read; a series gains its entry as soon as its first file imports.

- **Milestone**: M9 (m9-ux-diagnosability)
- **Source**: M9 finding F23 — freshly added, still-empty series rendered as empty shelves on the iPad reader.

#### Scenario: Empty series hidden by default

- **WHEN** the library holds a series with zero issue files and a reader requests the series feed
- **THEN** that series is absent from the feed while series with files render normally

#### Scenario: Config opt-out restores them

- **WHEN** the operator disables the file-less-series filter in configuration
- **THEN** file-less series render in the feed again (empty shelves permitted)
