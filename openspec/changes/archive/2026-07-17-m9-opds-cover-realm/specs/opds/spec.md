# opds — m9-opds-cover-realm deltas

## ADDED Requirements

### Requirement: FRG-OPDS-019 — Series cover served on the OPDS auth realm

The image and thumbnail links an OPDS feed advertises for a series SHALL resolve to a route on the OPDS authentication realm (`/opds/*`, HTTP Basic), never the web-UI/API-key perimeter, so a reader authenticated for the catalog can load the cover it is pointed at. The system SHALL serve the cached series cover at an OPDS-realm route addressed by integer series id (no request-controlled path component), returning the cached image with HEAD parity or a 404 when no cover is cached.

- **Milestone**: M9 (m9-opds-cover-realm)
- **Source**: On-device Panels couch test 2026-07-17 — covers 401'd because the feed advertised `/api/v1/series/{id}/cover`, off the OPDS Basic realm.
- **Notes**: The title-page fallback (FRG-OPDS-011) was already on the OPDS realm; only the cached-remote-cover branch was misrouted. Same id-only, root-fixed confinement as the other OPDS file routes (FRG-OPDS-003/004).

#### Scenario: A reader loads the cover the feed points it at

- **WHEN** an OPDS reader authenticated with Basic credentials fetches the image link advertised on an acquisition entry for a series that has a cached cover
- **THEN** the link is on the `/opds` realm, the Basic credentials are accepted, and the cached cover image bytes are returned

#### Scenario: HEAD parity and missing cover

- **WHEN** the OPDS series-cover route receives a HEAD, or a GET for a series with no cached cover
- **THEN** HEAD mirrors GET's status and content type with no body, and a missing cover yields 404
