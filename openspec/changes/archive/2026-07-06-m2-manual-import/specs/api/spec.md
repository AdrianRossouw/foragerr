## MODIFIED Requirements

### Requirement: FRG-API-015 — Manual import endpoint

The API SHALL expose manual-import endpoints that list candidate files under a given path with their would-be import decisions and rejection reasons, and accept user-corrected mappings (series/issue/format overrides) for execution through the same import pipeline as automatic imports.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §5.5 ManualImportService, §7.1 ManualImport.
- **Notes**: Resolution path for ImportBlocked queue items; pairs with the UI overlay. Listing is read-only (no disk mutation beyond inspection); execution enqueues a pp-pool command that drives `import_candidate`. Same envelope/`ApiError` conventions as the rest of the API.

#### Scenario: List candidates for a path with decisions and reasons

- **WHEN** `GET /api/v1/manual-import?path=<abs>` is called for a folder of archives
- **THEN** it returns one entry per candidate with its resolved `approved` verdict, verbatim `rejections`, suggested series/issue/format, and embedded-metadata summary (`comicInfoPresent`, `cvIssueId`, `verified`) — computed via `aggregate → build_evaluation → decide`, touching no disk beyond inspection.

#### Scenario: List candidates for a blocked download

- **WHEN** `GET /api/v1/manual-import?downloadId=<id>` is called for an `import_blocked` download
- **THEN** it reuses the completed-download intake (remote-path mapping + grab hints) and lists that download's files with their would-be decisions and reasons.

#### Scenario: Submit corrected mappings for execution

- **WHEN** `POST /api/v1/manual-import` is sent `{ files: [{ path, seriesId, issueId, format? }] }`
- **THEN** the overrides are validated and a `manual-import` command is enqueued on the pp-pool, returning `201` with a `CommandResource`; on completion the files that resolved import and the rest report their blocking reasons — the same pipeline and history as automatic import.

#### Scenario: Unreadable path or unknown download is a typed error

- **WHEN** the path cannot be resolved/read or the `downloadId` is unknown
- **THEN** the endpoint returns a typed `ApiError` (400/404) rather than a crash or an empty success.

#### Scenario: Override cannot force a rejected file past the safety specs

- **WHEN** a submitted mapping targets a corrupt archive or a below-floor/no-space file
- **THEN** execution still runs the full decision set and the file is reported blocked/failed with its reason — the API exposes no "force" that skips `ArchiveValidSpec`/`FreeSpaceSpec`/`JunkFilterSpec`.
