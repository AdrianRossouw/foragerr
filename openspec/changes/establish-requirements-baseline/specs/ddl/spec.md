# ddl Spec Delta

## ADDED Requirements


### Requirement: FRG-DDL-001 — DDL client behind the common abstraction

The built-in DDL downloader SHALL implement the standard download-client interface so DDL grabs receive a download id, appear in the same tracked-download state machine and queue view, and flow through the same completed/failed handling as SABnzbd downloads.

- **Milestone**: M1
- **Source**: sonarr-arch §4.1 (interface as the seam for SAB + DDL); mylar-ddl §3.2 (state smeared across globals/DB/queue — the anti-pattern)
- **Notes**: The central DDL design decision: no parallel Mylar-style DDL_QUEUE/ddl_info world with hand-synced state.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A DDL grab and a SAB grab are indistinguishable in the queue resource except for protocol/client fields; DDL failure feeds the standard blocklist + re-search loop.

### Requirement: FRG-DDL-002 — GetComics search provider

The system SHALL implement a GetComics search provider that queries the site's search URL through an escalating query ladder (quoted exact "name #issue (year)", unquoted, name #issue, name year), following result pagination with a configurable depth cap, de-duplicating by post URL, skipping weekly-roundup posts, and emitting normalized release records into the standard decision engine.

- **Milestone**: M1
- **Source**: mylar-ddl §1.3, §1.4, §5 (query ladder, pagination, dedupe); mylar-ddl §3.7 (no pagination cap — fixed here)
- **Notes**: Deliberate divergence: Mylar stops at the first result passing its own filter; foragerr feeds all parsed candidates to the shared decision engine so DDL results compete with (and are explainable like) usenet results.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A wanted issue findable on GetComics produces release candidates carrying title, size, post date, and post URL that are decided by the same specifications as Newznab releases.

### Requirement: FRG-DDL-003 — Versioned page adapter with fixtures

All GetComics HTML parsing (search pages and post pages) SHALL live behind a versioned adapter with recorded HTML fixtures and tests, and unrecognized page structure SHALL fail gracefully (log, skip, provider health warning) rather than mis-parse or crash.

- **Milestone**: M1
- **Source**: mylar-ddl §3.1 (DOM coupling weakness), §5 (defensive adapter requirement)
- **Notes**: Also drop Mylar's cached-HTML-as-source-of-truth for retries; retries re-fetch the live post page (staleness bug in mylar-ddl §3.1).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Fixture tests cover search-result and post-page parsing; feeding a redesigned/garbage page yields zero results plus a health warning, no exception.

### Requirement: FRG-DDL-004 — Link enumeration and host/quality selection

For a chosen post, the system SHALL enumerate all offered download links keyed by quality tier (HD-Upscaled / HD-Digital / SD / normal) and host (main server, mirror, Mega, MediaFire, Pixeldrain), select one via a user-configurable host priority order and quality preference (default prefer upscaled), and SHALL reject known paywall/shortener links outright.

- **Milestone**: M1
- **Source**: mylar-ddl §1.5 (aio-pulse parsing, DDL_PRIORITY_ORDER, DDL_PREFER_UPSCALED, sh.st rejection); mylar-ddl §3.3 (table-driven rewrite of the copy-pasted ladder)
- **Notes**: Selection logic table-driven, not Mylar's 150-line if-ladder. Quality tier feeds the format/edition scoring in SRCH prioritization rather than a private notion of quality.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A post offering Mega and main-server links selects per the configured order; an `sh.st` link is never fetched.

### Requirement: FRG-DDL-005 — Per-host failover

On a download or verification failure, the system SHALL record the failed link type for the item and retry the same release via the next untried host per the priority order; only when all hosts are exhausted SHALL the item be marked Failed and handed to the standard failed-download pipeline (blocklist + re-search, issue state restored to wanted).

- **Milestone**: M1
- **Source**: mylar-ddl §1.7 (link_type_failure loop, reverse_the_pack_snatch); mylar-ddl §3.3 (GC_Mirror dispatch typo — the bug class to test against)
- **Notes**: Failover state lives on the persisted queue item; a dispatch-table test enumerates every link type to a handler (regression-proofing Mylar's typo bug).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** With the main-server link returning an ad page, the item automatically retries via the next configured host; after all hosts fail, the issue is re-searched and the post blocklisted.

### Requirement: FRG-DDL-006 — Politeness and provider self-protection

GetComics page fetches SHALL be rate-limited to a configurable minimum interval (default 15 s) plus random jitter with last-run/hit statistics persisted per provider, and the provider SHALL back off or self-disable (via the shared provider back-off ladder) on HTTP 429/503, Cloudflare challenge detection, and connection failures.

- **Milestone**: M1
- **Source**: mylar-ddl §1.8 (politeness summary), §3.7 (no jitter/backoff gaps), §5
- **Notes**: Reuses IDX's back-off ladder — one mechanism, all providers. Actual file downloads are not inter-delayed (matching Mylar's reasoning) but remain serialized (below).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Search-page fetch timestamps are ≥ the configured interval apart with observable jitter; a simulated 429 escalates the provider's back-off and it is skipped by the next search.

### Requirement: FRG-DDL-007 — Persistent serialized download queue

DDL downloads SHALL run from a database-backed queue whose items (status queued/downloading/completed/failed, progress, link/host, provenance) survive restart with in-flight items resuming or re-queueing automatically, executed single-flight (max concurrency 1, configurable), with manual retry, resume, abort, and remove actions.

- **Milestone**: M1
- **Source**: mylar-ddl §1.6 (DDL_LOCK, ddl_info), §3.2 (restart loses queue order — fixed), §5; mylar-ddl §1.7 (webserve retry/resume/abort)
- **Notes**: This queue is the DDL client's internal engine; its items are projected through get-items() into the common tracked-download view (no second user-facing queue).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Restarting foragerr mid-download leaves the item queued/resumable without manual restore; two queued items never download concurrently.

### Requirement: FRG-DDL-008 — Download execution and size accounting

File downloads SHALL stream with a sane chunk size (≥64 KiB), 30 s connect/read timeouts, record expected size (from the search result or Content-Length) and bytes received, and SHALL fail an attempt whose response lacks a usable Content-Length after retry or whose final size mismatches the expected size beyond tolerance (click-bait/ad-page detection).

- **Milestone**: M1
- **Source**: mylar-ddl §1.6 (downloadit), §3.4 (weak size model), §3.6 (1 KiB chunks)
- **Notes**: Expected-size check is the fix for Mylar's display-only use of the scraped size.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A response with no Content-Length and non-archive content fails the attempt (triggering host failover); a truncated transfer is detected by size mismatch rather than imported.

### Requirement: FRG-DDL-009 — Safe resume by Range

Interrupted downloads SHALL resume by issuing a Range request from the local partial size, accepting the resume only when the server responds 206 with a Content-Range matching the requested offset; any other response (including 200 with full body) SHALL restart the download from zero, never appending.

- **Milestone**: M1
- **Source**: mylar-ddl §1.6 (DDL_AUTORESUME), §3.5 (resume trust flaw — fixed), §5
- **Notes**: Keeps Mylar's good idea, mandates the validation Mylar lacks.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A resume against a Range-honoring server continues from the offset; a server that ignores Range causes a clean restart, and the resulting file passes verification.

### Requirement: FRG-DDL-010 — Content verification before import

Every completed DDL file SHALL be verified before entering the import pipeline: magic-number check against the claimed type, full archive integrity (CRC) test for ZIP/RAR, and size sanity; verification failure SHALL count as a download failure (host failover, then failed handling).

- **Milestone**: M1
- **Source**: mylar-ddl §1.7 (check_file_condition), §4 (CRC does not authenticate — content checks needed), §5
- **Notes**: Deeper structural validation (cbz contains images) is the import pipeline's job (IMP area); this is the download-side gate.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A downloaded HTML error page named `.cbz` is rejected at verification and the next host is tried; a CRC-corrupt archive never reaches the library.

### Requirement: FRG-DDL-011 — Safe filename generation

The system SHALL name downloaded files itself from library metadata and the queue id, sanitized for the target filesystem, and SHALL NOT derive filenames from redirect-final URLs or any other attacker-controllable remote value.

- **Milestone**: M1
- **Source**: mylar-ddl §4 (untrusted HTML → filesystem paths), §5
- **Notes**: Security-mandatory in the same change as the downloader (FRG-PROC-006); STRIDE entry required.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A hostile redirect chain ending in a path-traversal-shaped name produces a file with a locally generated safe name inside the DDL directory; a path-escape test corpus passes.

### Requirement: FRG-DDL-012 — Outbound URL security

All DDL HTTP fetches SHALL enforce a per-provider scheme and host allowlist, a capped redirect chain with each hop re-validated against the allowlist, TLS certificate verification always on (no `verify=False` anywhere, including any solver service), and session cookies SHALL never be sent to hosts outside the provider's allowlist.

- **Milestone**: M1
- **Source**: mylar-ddl §4 (blind redirects/SSRF, verify=False on FlareSolverr), §5
- **Notes**: Mirror hosts get added to the allowlist per host adapter. Mylar's per-provider proxy split-tunneling is not carried over; proxy support, if ever added, is process-wide (B).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A scraped link to an internal address (SSRF probe) or an off-allowlist redirect hop is refused; a test asserts no code path disables TLS verification.

### Requirement: FRG-DDL-013 — Import handoff with provenance

Verified completed DDL downloads SHALL flow automatically into the standard import pipeline with provenance recorded (provider, post URL, selected host/link type, queue id) in history, and that provenance SHALL back DDL blocklist matching.

- **Milestone**: M1
- **Source**: mylar-ddl §5 (provenance requirement); sonarr-arch §4.3 (history data dict)
- **Notes**: Provenance replaces Mylar's `[__issueid__]` filename-tag hack for tying DDL files to issues — the download id join key does that job.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** An imported DDL issue's history shows the GetComics post URL and host used; a subsequently failed identical post is rejected as blocklisted.

### Requirement: FRG-DDL-014 — Pack and booktype recognition

The GetComics provider SHALL recognize multi-issue packs (issue ranges, volume packs, annuals inclusion) and booktypes (TPB/GN/HC/One-Shot) from post titles, filter multi-part pack pages to parts covering wanted issues, extract pack archives safely, and suppress duplicate searching for issues already covered by an in-flight pack download.

- **Milestone**: B
- **Source**: mylar-ddl §1.4 (check_for_pack), §1.5 (multi-part pages, pack_check), §1.7 (PACK_ISSUEIDS_DONT_QUEUE); mylar-fs SRCH (pack preference)
- **Notes**: High value for backfill, but substantial parser + multi-issue-grab complexity; M1 covers single issues (which packs' `id-1..n` parts reduce to). Safe-extraction requirement below travels with this feature.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Grabbing a `#1-25` pack for a series wanting 1–10 downloads only relevant parts, marks all covered issues, and the backlog search skips those issues while the pack is in flight.

### Requirement: FRG-DDL-015 — Safe archive extraction

Pack archive extraction SHALL occur only after verification and SHALL enforce entry-count and total-decompressed-size caps, reject path-traversal entries and symlinks/hardlinks, and extract into a dedicated staging directory.

- **Milestone**: B
- **Source**: mylar-ddl §4 (extractall unmitigated), §5
- **Notes**: Milestone tied to packs (the only extraction consumer). Security-mandatory in the same change that introduces extraction (FRG-PROC-006).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A zip-bomb and a zip containing `../` entries and symlinks are each rejected with the item marked failed; no file lands outside the staging directory.

### Requirement: FRG-DDL-016 — Cloudflare session handling

If Cloudflare clearance is required, the system SHALL support an optional FlareSolverr integration invoked over TLS-verified connections, persist clearance cookies with owner-only file permissions treated as credentials (never logged or exported in diagnostics), and self-disable the provider on unresolved challenges.

- **Milestone**: B
- **Source**: mylar-ddl §1.2, §4 (verify=False + plaintext cookie persistence — fixed), §5
- **Notes**: Ship M1 without a solver (fail-with-health-warning on challenge); add FlareSolverr only if GetComics challenges prove routine in practice. ToS-sensitive UA-spoofing/evasion posture is a conscious registry-recorded decision.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Cookies file is created 0600 and excluded from any diagnostic bundle; with FlareSolverr unconfigured and a challenge presented, the provider disables with a clear health message.

### Requirement: FRG-DDL-017 — Mirror host adapters

Mirror-host downloading (Mega, MediaFire, Pixeldrain) SHALL be implemented as pluggable per-host adapters behind a common host-downloader interface consumed by the failover mechanism, each with its own allowlist entries and rate/captcha error detection.

- **Milestone**: B
- **Source**: mylar-ddl §1.6 (host dispatch), mylar-fs DDL (mirror downloaders with failover)
- **Notes**: M1 ships the main-server adapter only; failover machinery (above) is M1 so the first mirror adapter is pure addition. Mega first (most common mirror), per Mylar's default priority order.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Adding a host adapter requires no change to queue, failover, or verification code; Pixeldrain rate-limit responses surface as retryable host failures.
