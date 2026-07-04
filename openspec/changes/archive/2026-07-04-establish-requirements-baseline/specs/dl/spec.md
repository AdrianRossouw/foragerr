# dl Spec Delta

## ADDED Requirements


### Requirement: FRG-DL-001 — Download client abstraction

Download clients SHALL implement one interface — download(release) → client-side download id; get-items() → items with download id, title, category, total/remaining size, estimated time, output path, and status (Queued/Paused/Downloading/Completed/Failed/Warning); remove-item(delete data); get-status(); mark-imported — with SABnzbd and the built-in DDL client as the two baseline implementations.

- **Milestone**: M1
- **Source**: sonarr-arch §4.1 (IDownloadClient, DownloadClientItem)
- **Notes**: This seam is what makes DDL "just another client" instead of Mylar's parallel DDL_QUEUE world — the central DL design decision.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** The tracking loop and queue view operate identically over a SABnzbd item and a DDL item through the interface alone.

### Requirement: FRG-DL-002 — Client configuration and selection

Download clients SHALL be stored as provider configuration rows (implementation + JSON settings, enable flag, priority, remove-completed-downloads flag) with a schema endpoint and live test action, and grab dispatch SHALL select an enabled client matching the release's protocol, treating client failure as a fallback/pending condition rather than a lost grab.

- **Milestone**: M1
- **Source**: sonarr-arch §4.1 (DownloadClientProvider), §2.1, §7.2
- **Notes**: Baseline has at most one client per protocol, but the priority/round-robin shape is kept so a second client is config, not code.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A usenet release routes to SABnzbd and a DDL release to the DDL client with both configured; disabling SABnzbd makes usenet grabs fail visibly (pending/error), not vanish.

### Requirement: FRG-DL-003 — SABnzbd add via file upload

To grab a usenet release, the system SHALL itself fetch the NZB bytes from the indexer (with retry), validate them, and POST them to SABnzbd with `mode=addfile`, a dedicated configurable category (default "comics"), and a configurable priority, treating an empty `nzo_id` response as a grab failure.

- **Milestone**: M1
- **Source**: sonarr-arch §4.2 (UsenetClientBase.Download, mode=addfile)
- **Notes**: Deliberate divergence from Mylar's add-by-URL flow (SAB pulling the NZB back from Mylar's API with a one-time download key) — that scheme adds an extra auth surface and a callback dependency; recommend permanent exclusion (mylar-fs DL). Server-side fetch keeps indexer credentials off SAB and allows NZB validation.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A grab produces an item in SABnzbd's "comics" category whose nzo_id is recorded; an indexer 404 on the NZB fetch surfaces as a failed grab with reason.

### Requirement: FRG-DL-004 — SABnzbd queue and history polling

The SABnzbd client SHALL read queue (`mode=queue`) and history (`mode=history`) filtered to its configured category, normalizing sizes to bytes and mapping SAB states onto the common item status (paused→Paused; Queued/Grabbing/Propagating→Queued; Verifying/Extracting/Repairing→Downloading; history Failed→Failed with disk-full unpack as Warning; Completed→Completed), and SHALL flag `ENCRYPTED/`-prefixed items as encrypted.

- **Milestone**: M1
- **Source**: sonarr-arch §4.2 (GetItems, status mapping)
- **Notes**: Version check (`mode=version`) and config sanity (`mode=get_config`) belong in the client test action.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Each SAB state in a fixture set maps to the documented common status; items in other categories never appear.

### Requirement: FRG-DL-005 — Remote path mapping

The system SHALL support per-client remote-path-to-local-path mappings applied to client-reported output paths, so completed downloads are importable when the client runs on another host or container.

- **Milestone**: M1
- **Source**: sonarr-arch §4.2 (RemotePathMappings), §4.5 (path validation); mylar-fs DL (cdh_mapping)
- **Notes**: Docker deployment target makes this near-certain to be needed on day one.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** With SAB reporting `/downloads/complete/x` mapped to `/mnt/sab/complete/x`, import reads the mapped path; an unmapped foreign path yields a "check remote path mapping" warning, not a silent failure.

### Requirement: FRG-DL-006 — Grab history with download-id join key

Every successful grab SHALL write one Grabbed history record per issue carrying the client download id plus release data (indexer, guid, title, size, download URL, publish date, protocol, score), and the download id SHALL be the join key for all subsequent tracking, import, and failure handling.

- **Milestone**: M1
- **Source**: sonarr-arch §4.3 (EpisodeGrabbedEvent, HistoryService)
- **Notes**: Replaces Mylar's `nzblog` name-normalization handshake (fragile string matching) with an id join — a deliberate, important divergence.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Given a tracked item's download id, the originating grab record with full release data is retrievable; a grab spanning a multi-issue release yields one record per issue sharing the id.

### Requirement: FRG-DL-007 — Tracked-download state machine

A tracking refresh (scheduled ~every 1 minute, plus event-triggered on grab/import) SHALL list items from all enabled clients, match each to grab history by download id (re-parsing the title as secondary evidence), and maintain a per-download state in {Downloading, ImportBlocked, ImportPending, Importing, Imported, FailedPending, Failed, Ignored} with an Ok/Warning/Error status and human-readable status messages.

- **Milestone**: M1
- **Source**: sonarr-arch §4.4 (DownloadMonitoringService, TrackedDownloadService)
- **Notes**: Keep Sonarr's check (fast, every refresh) vs process (slow, state-advancing) separation as an implementation hint.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A grabbed release progresses through Downloading → ImportPending → Importing → Imported observably; each transition is recorded; an unmatched foreign item in the category becomes Ignored/warning, not a crash.

### Requirement: FRG-DL-008 — Queue view from tracked downloads

The user-facing queue SHALL be built exclusively from tracked-download state (paged API resource with series/issue linkage, size/remaining, status, state, status messages, download id, client, output path), and no user-facing surface SHALL poll the download client directly.

- **Milestone**: M1
- **Source**: sonarr-arch §4.4 (QueueService), §7.3 (QueueResource)
- **Notes**: Queue actions (remove, with/without data; manual import for blocked items) ride on this resource.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Queue contents update within one tracking interval of client-side changes; queue rows expose rejection/status messages for warning states.

### Requirement: FRG-DL-009 — Completed download handling

When a tracked item reports Completed, the system SHALL validate its (mapped) output path, resolve the series/issues from grab history or parsing — moving unresolvable items to ImportBlocked with a manual-interaction-required signal — and otherwise advance ImportPending → Importing → run the shared import pipeline → Imported when all grabbed issues imported, or back to ImportBlocked with per-file messages on partial/rejected import.

- **Milestone**: M1
- **Source**: sonarr-arch §4.5 (CompletedDownloadService)
- **Notes**: The import pipeline itself is the IMP area; this requirement owns the state transitions and the blocked-not-lost guarantee. Double post-processing cannot occur by construction: external completion scripts (Mylar's ComicRN) are excluded — CDH polling is the only intake (mylar-fs PP path 1 recommended as permanent exclusion).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A completed SAB item is imported and renamed without user action; a completed item whose title cannot be mapped appears as import-blocked with a reason and is resolvable via manual import.

### Requirement: FRG-DL-010 — Post-import client cleanup

After a download reaches Imported, the system SHALL remove the item (and its data) from the download client if and only if the per-client remove-completed-downloads flag is enabled.

- **Milestone**: M1
- **Source**: sonarr-arch §4.5 (DownloadEventHub)
- **Notes**: Mark-imported prevents reprocessing loops when cleanup is disabled.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** With the flag on, the SAB history entry is deleted after import; with it off, the entry remains and is marked imported so it is not re-processed.

### Requirement: FRG-DL-011 — Failed download handling

Tracked items reporting Failed, or flagged encrypted/password-protected, SHALL transition to FailedPending and then Failed, emitting a failure event that carries the affected series/issues, source title, and the grab data needed for blocklisting.

- **Milestone**: M1
- **Source**: sonarr-arch §4.6 (FailedDownloadService)
- **Notes**: DDL failures (after host exhaustion) feed this same path — one failure pipeline for both protocols.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A password-protected NZB completes in SAB as encrypted and ends Failed in foragerr with the grab's issues identified.

### Requirement: FRG-DL-012 — Blocklist

Failed downloads SHALL be recorded in a blocklist (series, issue ids, source title, indexer, size, publish date, protocol), future candidates SHALL be matched against it (usenet: same title + indexer + size + publish date; DDL: source URL/title; torrents at M2: info-hash or title) producing a permanent rejection, and the blocklist SHALL be user-viewable and removable via a paged resource.

- **Milestone**: M1
- **Source**: sonarr-arch §4.6 (BlocklistService, SameNzb match), §3.2 (BlocklistSpecification); mylar-fs SRCH (failed-result blacklist)
- **Notes**: Mylar blocklists by provider result ID only; Sonarr's multi-field match also catches the same bad post re-surfacing under a new guid — adopt Sonarr's.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** After a release fails, the identical release from the same indexer is rejected "blocklisted" in the next search; deleting the blocklist row makes it grabbable again.

### Requirement: FRG-DL-013 — Automatic re-search after failure

When a download fails and auto-redownload is enabled (default on), the system SHALL immediately queue a new search command for the affected issues, which — combined with the blocklist — selects a different release.

- **Milestone**: M1
- **Source**: sonarr-arch §4.6 (RedownloadFailedDownloadService — the self-healing loop)
- **Notes**: This closes the loop the whole acquisition pipeline exists for: bad/password-protected scans self-correct.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A failed grab is followed, without user action, by a search that grabs an alternative release while the failed one is rejected as blocklisted.

### Requirement: FRG-DL-014 — SABnzbd retry passthrough

The system SHALL expose SABnzbd's retry capability for failed items from the queue view (`mode=retry`) as a manual action, distinct from foragerr-level re-search.

- **Milestone**: B
- **Source**: sonarr-arch §4.2 (proxy call inventory incl. mode=retry)
- **Notes**: Convenience, not correctness — the M1 answer to failures is blocklist + re-search.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A SAB item failed on a transient unpack error can be retried in place from foragerr's queue.
