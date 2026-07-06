# DL — Download Clients (Usenet) Specification

## Purpose

Baseline requirements for download clients (usenet), mined from the
Phase 1 reference research (`docs/research/`). Baseline depth per the Phase 2 scope
decision: SHALL + coarse acceptance; scenario-level elaboration happens in the
milestone change that implements each requirement (FRG-PROC-003, FRG-PROC-009).
## Requirements
### Requirement: FRG-DL-001 — Download client abstraction

Download clients SHALL implement one interface — download(release) → client-side download id; get-items() → items with download id, title, category, total/remaining size, estimated time, output path, and status (Queued/Paused/Downloading/Completed/Failed/Warning); remove-item(delete data); get-status(); mark-imported — with SABnzbd and the built-in DDL client as the two baseline implementations.

- **Milestone**: M1
- **Source**: sonarr-arch §4.1 (IDownloadClient, DownloadClientItem)
- **Notes**: This seam is what makes DDL "just another client" instead of Mylar's parallel DDL_QUEUE world — the central DL design decision.

#### Scenario: One DownloadClient protocol implemented by both clients

- **WHEN** the SABnzbd client and the built-in DDL client are each instantiated
- **THEN** both expose the same `DownloadClient` protocol surface — `test()`, `download(release) → download_id`, `get_items() → list[ClientItem]`, `remove(item, delete_data)`, and `mark_imported(item)` — with no client-specific methods reachable by the tracking loop

#### Scenario: get_items yields a uniform typed ClientItem

- **WHEN** `get_items()` is called on either client
- **THEN** every returned `ClientItem` carries download_id, title, category, total_size and remaining_size in bytes, estimated_time, output_path, and a status drawn from the common enum {queued, paused, downloading, completed, failed, warning}, regardless of the underlying client's native shape

#### Scenario: Tracking and queue operate through the interface alone

- **WHEN** the tracking loop and queue view process one SABnzbd item and one DDL item
- **THEN** each is handled identically through the `DownloadClient` protocol without branching on the concrete client type

### Requirement: FRG-DL-002 — Client configuration and selection

Download clients SHALL be stored as provider configuration rows (implementation + JSON settings, enable flag, priority, remove-completed-downloads flag) with a schema endpoint and live test action, and grab dispatch SHALL select an enabled client matching the release's protocol, treating client failure as a fallback/pending condition rather than a lost grab.

- **Milestone**: M1
- **Source**: sonarr-arch §4.1 (DownloadClientProvider), §2.1, §7.2
- **Notes**: Baseline has at most one client per protocol, but the priority/round-robin shape is kept so a second client is config, not code.

#### Scenario: Provider table mirrors the indexer contract

- **WHEN** a download client is configured
- **THEN** it is persisted as a `download_clients` provider row (implementation, JSON settings, enable flag, priority, remove-completed-downloads flag) whose settings contract, `GET /api/v1/downloadclient/schema`, and `POST /api/v1/downloadclient/test` endpoints mirror the indexer provider table shape

#### Scenario: Protocol-matched dispatch

- **WHEN** a usenet release and a DDL release are each grabbed with both clients enabled
- **THEN** the usenet release routes to SABnzbd and the DDL release routes to the built-in DDL client, selected by matching the release protocol to an enabled client

#### Scenario: Client unreachable at grab is retryable, never lost

- **WHEN** the protocol-matched client is unreachable at grab time
- **THEN** the grab returns a typed command failure, the release cache entry remains valid, and the grab can be retried — the release is never silently dropped

### Requirement: FRG-DL-003 — SABnzbd add via file upload

To grab a usenet release, the system SHALL itself fetch the NZB bytes from the indexer (with retry), validate them, and POST them to SABnzbd with `mode=addfile`, a dedicated configurable category (default "comics"), and a configurable priority, treating an empty `nzo_id` response as a grab failure.

- **Milestone**: M1
- **Source**: sonarr-arch §4.2 (UsenetClientBase.Download, mode=addfile)
- **Notes**: Deliberate divergence from Mylar's add-by-URL flow (SAB pulling the NZB back from Mylar's API with a one-time download key) — that scheme adds an extra auth surface and a callback dependency; recommend permanent exclusion (mylar-fs DL). Server-side fetch keeps indexer credentials off SAB and allows NZB validation.

#### Scenario: Server-side NZB fetch through the indexer back-off ladder

- **WHEN** a usenet release is grabbed
- **THEN** foragerr fetches the NZB bytes server-side from the indexer via the external egress profile, subject to the indexer's back-off ladder, so indexer credentials never reach SABnzbd

#### Scenario: NZB validation before upload

- **WHEN** fetched NZB bytes are validated before upload
- **THEN** they must be non-empty, parse under defusedxml, and contain at least one file segment; bytes failing any check surface as a failed grab with a reason and are never POSTed to SABnzbd

#### Scenario: addfile multipart upload records nzo_id as download_id

- **WHEN** validated NZB bytes are uploaded with `mode=addfile` as a multipart POST carrying the configured category (default "comics") and priority
- **THEN** the returned `nzo_id` is recorded as the download_id; an empty `nzo_id` response is treated as a grab failure

#### Scenario: Local-service egress to the operator base URL

- **WHEN** foragerr connects to the SABnzbd HTTP API
- **THEN** the request uses the local-service egress profile against the operator-configured base URL, distinct from the external profile used to fetch NZBs from indexers

### Requirement: FRG-DL-004 — SABnzbd queue and history polling

The SABnzbd client SHALL read queue (`mode=queue`) and history (`mode=history`) filtered to its configured category, normalizing sizes to bytes and mapping SAB states onto the common item status (paused→Paused; Queued/Grabbing/Propagating→Queued; Verifying/Extracting/Repairing→Downloading; history Failed→Failed with disk-full unpack as Warning; Completed→Completed), and SHALL flag `ENCRYPTED/`-prefixed items as encrypted.

- **Milestone**: M1
- **Source**: sonarr-arch §4.2 (GetItems, status mapping)
- **Notes**: Version check (`mode=version`) and config sanity (`mode=get_config`) belong in the client test action.

#### Scenario: Queue and history merged, category-filtered

- **WHEN** `get_items()` polls `mode=queue` and `mode=history`
- **THEN** the results are concatenated and filtered to the configured category, sizes are normalized to bytes, and items in any other category never appear

#### Scenario: SAB states map to typed ClientItem states

- **WHEN** each SAB status in a fixture set is mapped
- **THEN** paused→paused; Queued/Grabbing/Propagating→queued; Verifying/Extracting/Repairing→downloading; Completed→completed; history Failed→failed, except a disk-full unpack message which maps to a warning

#### Scenario: Encrypted / password history reported as failed with reason

- **WHEN** a history item is `ENCRYPTED/`-prefixed or otherwise password-protected
- **THEN** it is flagged encrypted and reported as a failed ClientItem carrying the encryption reason

### Requirement: FRG-DL-005 — Remote path mapping

The system SHALL support per-client remote-path-to-local-path mappings applied to client-reported output paths, so completed downloads are importable when the client runs on another host or container.

- **Milestone**: M1
- **Source**: sonarr-arch §4.2 (RemotePathMappings), §4.5 (path validation); mylar-fs DL (cdh_mapping)
- **Notes**: Docker deployment target makes this near-certain to be needed on day one.

#### Scenario: Mapping table rewrites completed paths

- **WHEN** a completed item's output path matches a remote-path-mapping row (host + remote prefix)
- **THEN** the remote prefix is rewritten to the configured local prefix and import reads the mapped local path

#### Scenario: Unmapped foreign path warns rather than fails silently

- **WHEN** a completed item's path is foreign (e.g. a different-OS or unmapped prefix) with no matching mapping row
- **THEN** the item is surfaced with a "check remote path mapping" warning instead of a silent import failure

### Requirement: FRG-DL-006 — Grab history with download-id join key

Every successful grab SHALL write one Grabbed history record per issue carrying the client download id plus release data (indexer, guid, title, size, download URL, publish date, protocol, score), and the download id SHALL be the join key for all subsequent tracking, import, and failure handling.

- **Milestone**: M1
- **Source**: sonarr-arch §4.3 (EpisodeGrabbedEvent, HistoryService)
- **Notes**: Replaces Mylar's `nzblog` name-normalization handshake (fragile string matching) with an id join — a deliberate, important divergence.

#### Scenario: grab_history row written at grab as the join key

- **WHEN** a release is grabbed
- **THEN** a `grab_history` row is written carrying download_id, issue, release guid/title/indexer, size, and provenance source (`indexer` or `ddl`), and download_id is the sole join key used by tracking, import, and failure handling

#### Scenario: Multi-issue release yields one row per issue sharing the id

- **WHEN** a single release spans multiple grabbed issues
- **THEN** one `grab_history` row is written per issue, all sharing the same download_id

#### Scenario: Retrieval by download_id returns full release data

- **WHEN** a tracked item's download_id is used to look up its originating grab
- **THEN** the `grab_history` row with its full release data (guid, title, indexer, size, source) is returned

### Requirement: FRG-DL-007 — Tracked-download state machine

A tracking refresh (scheduled ~every 1 minute, plus event-triggered on grab/import) SHALL list items from all enabled clients, match each to grab history by download id (re-parsing the title as secondary evidence), and maintain a per-download state in {Downloading, ImportBlocked, ImportPending, Importing, Imported, FailedPending, Failed, Ignored} with an Ok/Warning/Error status and human-readable status messages.

- **Milestone**: M1
- **Source**: sonarr-arch §4.4 (DownloadMonitoringService, TrackedDownloadService)
- **Notes**: Keep Sonarr's check (fast, every refresh) vs process (slow, state-advancing) separation as an implementation hint.

#### Scenario: TrackDownloadsCommand matches client items by download_id

- **WHEN** the ~1-minute `TrackDownloadsCommand` runs over the download pool (also event-triggered on grab/import)
- **THEN** it lists items from all enabled clients and matches each to its `grab_history` row by download_id

#### Scenario: Unmatched item re-parsed via the single parser, adopt-or-unknown

- **WHEN** a client item has no matching download_id
- **THEN** its title is re-parsed through the single parser (an issue-id tag wins over heuristics) and it is either adopted onto a known issue or recorded as unknown — never crashing the refresh

#### Scenario: State transitions emit events and are restart-safe

- **WHEN** a tracked download advances grabbed → downloading → import_pending (completed, awaiting the change-6 import pipeline) | failed | ignored
- **THEN** each `tracked_downloads.state` transition is persisted with an ok/warning/error status and message, emits an event, and survives process restart

### Requirement: FRG-DL-008 — Queue view from tracked downloads

The user-facing queue SHALL be built exclusively from tracked-download state (paged API resource with series/issue linkage, size/remaining, status, state, status messages, download id, client, output path), and no user-facing surface SHALL poll the download client directly.

- **Milestone**: M1
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

### Requirement: FRG-DL-009 — Completed download handling

When a tracked item reports Completed, the system SHALL validate its (mapped) output path, resolve the series/issues from grab history or parsing — moving unresolvable items to ImportBlocked with a manual-interaction-required signal — and otherwise advance ImportPending → Importing → run the shared import pipeline → Imported when all grabbed issues imported, or back to ImportBlocked with per-file messages on partial/rejected import.

- **Milestone**: M1
- **Source**: sonarr-arch §4.5 (CompletedDownloadService)
- **Notes**: The import pipeline itself is the IMP area; this requirement owns the state transitions and the blocked-not-lost guarantee. Double post-processing cannot occur by construction: external completion scripts (Mylar's ComicRN) are excluded — CDH polling is the only intake (mylar-fs PP path 1 recommended as permanent exclusion).

#### Scenario: ProcessImports drains import-pending items through the shared pipeline to Imported

- **WHEN** the periodic ProcessImportsCommand (~1-minute cadence, running on the post-processing pool) drains a tracked download in state ImportPending whose mapped output path is valid and whose grabbed issues all resolve
- **THEN** the item is advanced to Importing, run through the one shared import pipeline (verify → aggregate → decide → rename-into-library via safe-join → issue_files row committed), transitioned to Imported once every grabbed issue is imported, and an import-history event is recorded for the download id

#### Scenario: Unresolvable completed item is blocked with a visible, persisted reason

- **WHEN** a completed item's series/issues cannot be resolved from grab history or title parsing
- **THEN** the item is moved to ImportBlocked carrying a manual-interaction-required signal and a human-readable reason, the reason is persisted and surfaced on the queue resource, and no file is auto-deleted or silently dropped

#### Scenario: Partial or rejected import blocks with per-file reasons and stays retryable

- **WHEN** the shared pipeline rejects some but not all grabbed issues (or all of them) during import
- **THEN** the item returns to ImportBlocked with per-file messages, the download and its staged evidence are retained (blocked-not-lost), and the item remains eligible for re-processing on a later ProcessImports run after user action or when the evidence changes

#### Scenario: Blocked item re-processes to Imported once evidence changes, without re-grab

- **WHEN** a previously ImportBlocked item's blocking condition is resolved (e.g. the operator supplies the mapping via manual import, or metadata now resolves the issue)
- **THEN** the next ProcessImports run re-processes the same retained download through the shared pipeline and advances it to Imported without requiring a fresh grab

### Requirement: FRG-DL-010 — Post-import client cleanup

After a download reaches Imported, the system SHALL remove the item (and its data) from the download client if and only if the per-client remove-completed-downloads flag is enabled.

- **Milestone**: M1
- **Source**: sonarr-arch §4.5 (DownloadEventHub)
- **Notes**: Mark-imported prevents reprocessing loops when cleanup is disabled.

#### Scenario: Successful import with remove-completed enabled removes the client item and data

- **WHEN** a download reaches Imported (its issue_files row committed) and the source client's remove-completed-downloads flag is enabled
- **THEN** the client's mark_imported/remove is invoked to delete the item and its data, and — for a DDL grab — the DDL staging files are removed only after that import success

#### Scenario: Successful import with remove-completed disabled marks imported but leaves the item

- **WHEN** a download reaches Imported and the source client's remove-completed-downloads flag is disabled
- **THEN** the client item is marked imported (so it is not re-processed) but neither the item, its data, nor its DDL staging files are removed

#### Scenario: Failed or blocked download is never cleaned from the client

- **WHEN** a tracked download is in ImportBlocked, FailedPending, or Failed rather than Imported
- **THEN** no client removal, mark_imported, or DDL staging cleanup occurs regardless of the remove-completed-downloads flag, so the source evidence remains available for retry

### Requirement: FRG-DL-011 — Failed download handling

Tracked items reporting Failed, or flagged encrypted/password-protected, SHALL transition to FailedPending and then Failed, emitting a failure event that carries the affected series/issues, source title, and the grab data needed for blocklisting.

- **Milestone**: M1
- **Source**: sonarr-arch §4.6 (FailedDownloadService)
- **Notes**: DDL failures (after host exhaustion) feed this same path — one failure pipeline for both protocols.

#### Scenario: Failed / encrypted / vanished converge to state failed

- **WHEN** a tracked item reports failed, is flagged encrypted/password-protected, or has vanished from the client
- **THEN** it transitions to state failed and emits a failure event carrying the affected series/issues, source title, and the grab data (guid, indexer, title, size, download_id, source) needed for blocklisting

#### Scenario: Both protocols feed one failure path

- **WHEN** a DDL download fails after host exhaustion or a usenet download completes encrypted in SABnzbd
- **THEN** both drive the identical failed transition and failure event, with the grab's issues correctly identified

### Requirement: FRG-DL-012 — Blocklist

Failed downloads SHALL be recorded in a blocklist (series, issue ids, source title, indexer, size, publish date, protocol), future candidates SHALL be matched against it (usenet: same title + indexer + size + publish date; DDL: source URL/title; torrents at M2: info-hash or title) producing a permanent rejection, and the blocklist SHALL be user-viewable and removable via a paged resource.

- **Milestone**: M1
- **Source**: sonarr-arch §4.6 (BlocklistService, SameNzb match), §3.2 (BlocklistSpecification); mylar-fs SRCH (failed-result blacklist)
- **Notes**: Mylar blocklists by provider result ID only; Sonarr's multi-field match also catches the same bad post re-surfacing under a new guid — adopt Sonarr's.

#### Scenario: Failure writes a multi-field blocklist row

- **WHEN** the failure event fires
- **THEN** a blocklist row is written capturing guid, indexer, title, size, download_id, and source, so the same bad post is caught even if it resurfaces under a new guid

#### Scenario: BlocklistSpecification rejects a matching candidate live

- **WHEN** the change-4 `BlocklistSpecification` evaluates a future candidate against the live blocklist store (usenet: same title + indexer + size + publish date; DDL: source URL/title)
- **THEN** a matching candidate is permanently rejected as "blocklisted"

#### Scenario: Blocklist row is user-removable and re-enables grabbing

- **WHEN** a user deletes a blocklist row via the paged blocklist resource
- **THEN** the previously rejected release becomes grabbable again in the next search

### Requirement: FRG-DL-013 — Automatic re-search after failure

When a download fails and auto-redownload is enabled (default on), the system SHALL immediately queue a new search command for the affected issues, which — combined with the blocklist — selects a different release.

- **Milestone**: M1
- **Source**: sonarr-arch §4.6 (RedownloadFailedDownloadService — the self-healing loop)
- **Notes**: This closes the loop the whole acquisition pipeline exists for: bad/password-protected scans self-correct.

#### Scenario: Failure enqueues an automatic IssueSearchCommand

- **WHEN** a download reaches state failed with auto-redownload enabled (default on)
- **THEN** an `IssueSearchCommand` for the affected issues is enqueued automatically without user action

#### Scenario: Re-search selects a different release, avoiding the failed one

- **WHEN** the auto-enqueued search runs
- **THEN** the change-4 already-queued and blocklist specifications evaluate the live stores so the just-failed release is rejected as blocklisted and an alternative release is grabbed

#### Scenario: Dedup guards prevent re-search storms

- **WHEN** multiple failures for the same issues occur in close succession
- **THEN** dedup guards collapse the enqueued searches so a storm of duplicate `IssueSearchCommand`s is not created

### Requirement: FRG-DL-014 — SABnzbd retry passthrough

The system SHALL expose SABnzbd's retry capability for failed items from the queue view (`mode=retry`) as a manual action, distinct from foragerr-level re-search.

- **Milestone**: B
- **Source**: sonarr-arch §4.2 (proxy call inventory incl. mode=retry)
- **Notes**: Convenience, not correctness — the M1 answer to failures is blocklist + re-search.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A SAB item failed on a transient unpack error can be retried in place from foragerr's queue.

