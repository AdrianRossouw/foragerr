## MODIFIED Requirements

### Requirement: FRG-API-007 — Queue endpoint backed by tracked downloads

The API SHALL expose a paged `GET /queue` built from tracked downloads (not live client polling per request), each record carrying seriesId/issueId, nested series/issue, size/sizeleft, tracked-download status (ok/warning/error) and state, status messages, downloadId, client and indexer names, and estimated completion; with `DELETE /queue/{id}` supporting remove (optionally deleting data and/or blocklisting).

- **Milestone**: M1
- **Source**: sonarr-architecture.md §4.4 queue tracking loop and QueueService, §7.3 QueueResource shape, §7.1 queue actions.
- **Notes**: The tracking state machine itself is DL area; this owns the read/remove HTTP surface. "Nothing user-facing polls SAB directly" is the load-bearing property.

#### Scenario: Paged envelope over tracked_downloads joined to library

- **WHEN** `GET /api/v1/queue` is requested
- **THEN** it returns the standard paged envelope whose records are built from `tracked_downloads` joined to series/issues, each carrying seriesId/issueId, nested series/issue, size/sizeleft, status (ok/warning/error), state, status messages, downloadId, client and indexer names, and estimated completion

#### Scenario: Never a live client call at request time

- **WHEN** the queue endpoint serves a request
- **THEN** it reads only persisted tracked-download state and makes no live download-client call, so a grabbed release appears with downloading state within one tracking cycle rather than on demand

#### Scenario: import_pending and import_blocked are visible

- **WHEN** tracked downloads are in import_pending or import_blocked state
- **THEN** they appear in the `GET /queue` result with those states and their status messages, giving the user visibility into items awaiting or blocked from import

#### Scenario: DELETE removes with optional blocklist

- **WHEN** `DELETE /api/v1/queue/{id}?blocklist=<bool>` is called (optionally requesting data deletion)
- **THEN** the item is manually removed from the queue, the download client is instructed to remove it (and its data when requested), and a blocklist row is written when `blocklist=true`
