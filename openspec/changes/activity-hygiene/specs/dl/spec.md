# dl — delta for activity-hygiene

## MODIFIED Requirements

### Requirement: FRG-DL-008 — Queue view from tracked downloads

The user-facing queue SHALL be built exclusively from tracked-download state
(paged API resource with series/issue linkage, size/remaining, status,
state, status messages, download id, client, output path), and no
user-facing surface SHALL poll the download client directly. The queue
SHALL offer a bulk remove: one request naming multiple tracked rows,
applying the single remove's exact per-row semantics (a row mid-import is
refused for that row only; the optional blocklist write uses the shared
multi-field key; client-side removal is best-effort and never blocks
de-tracking) and returning a per-row applied/errors report.

- **Milestone**: M1; bulk remove added in activity-hygiene.
- **Source**: sonarr-arch §4.4 (QueueService), §7.3 (QueueResource)
- **Notes**: Queue actions (remove, with/without data; manual import for blocked items) ride on this resource.

#### Scenario: Queue served from tracked_downloads, never a live client call

- **WHEN** the queue resource is requested
- **THEN** it is assembled from `tracked_downloads` joined to series/issues with size/remaining, status, state, status messages, download_id, client, and output path — with no live download-client call made at request time

#### Scenario: import_pending visibility

- **WHEN** a tracked download is in import_pending or import_blocked state
- **THEN** it remains visible in the queue view with its state and status messages, rather than disappearing once the client reports completed

#### Scenario: Queue reflects client changes within one tracking cycle

- **WHEN** a client-side change occurs (item completes or fails)
- **THEN** the queue reflects the new tracked-download state within one tracking interval, driven by the tracking refresh rather than by any user-facing poll of the client


#### Scenario: Bulk remove applies single-remove semantics per row

- **WHEN** a bulk remove names several tracked rows, one of which is
  mid-import
- **THEN** every other row is de-tracked (with blocklist/delete-data as
  requested), the importing row is refused with its reason in the
  per-row errors, and the client-removal step failing for one row never
  prevents its de-tracking
