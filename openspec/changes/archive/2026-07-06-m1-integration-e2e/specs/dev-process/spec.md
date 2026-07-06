## ADDED Requirements

### Requirement: FRG-PROC-010 — End-to-end slice verification harness

The project SHALL maintain a browser-driven end-to-end suite (Playwright) that
exercises the deployed application against its real container image — external
services mocked by default, optionally live via env-gated credentials — covering at
minimum: adding a series, interactive search with visible rejection reasons, grab →
download → automatic import → correctly renamed library file, library browsing in
the UI, and OPDS feed navigation with a file download served under the correct
comic MIME type. The suite SHALL run headless from a single command, capture
screenshots and traces on failure, and SHALL be green before a milestone is
presented for owner review.

#### Scenario: Hermetic slice run passes from one command

- **WHEN** the e2e entrypoint runs against a freshly built image with fixture
  ComicVine/indexer/DDL services and an empty /config volume
- **THEN** the suite drives first-run health, series add, interactive search
  (rejection reasons rendered verbatim), grab, import, UI browse, and OPDS download
  (byte-identical file, `application/vnd.comicbook+zip`) to a green verdict with no
  manual steps

#### Scenario: Failure produces actionable artifacts

- **WHEN** any e2e step fails
- **THEN** the runner saves a screenshot and Playwright trace for the failing step
  and the run exits non-zero naming the failed scenario

#### Scenario: Live tier is gated and optional

- **WHEN** news-server/API credentials are absent from the environment
- **THEN** the live-SABnzbd tier is skipped (reported as skipped, not failed) and
  the hermetic verdict is unaffected; with credentials present, the tier completes
  one real small download through to import

#### Scenario: Milestone review gate

- **WHEN** a milestone is presented for owner review
- **THEN** the most recent e2e run against that milestone's image is green and its
  run log is referenced in the review material

#### Scenario: Acceptance report is generated, not authored

- **WHEN** the e2e suite completes a milestone-acceptance run
- **THEN** an acceptance report is generated mechanically from the FRG-tagged
  scenario results (scenario → tagged requirement ids → pass/fail/skipped) with no
  hand-authored criteria matrix, and the owner's sign-off is recorded against that
  generated report in the change proposal's `## Acceptance` section
