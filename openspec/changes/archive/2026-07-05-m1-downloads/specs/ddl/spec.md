## MODIFIED Requirements

### Requirement: FRG-DDL-001 — DDL client behind the common abstraction

The built-in DDL downloader SHALL implement the standard download-client interface so DDL grabs receive a download id, appear in the same tracked-download state machine and queue view, and flow through the same completed/failed handling as SABnzbd downloads.

- **Milestone**: M1
- **Source**: sonarr-arch §4.1 (interface as the seam for SAB + DDL); mylar-ddl §3.2 (state smeared across globals/DB/queue — the anti-pattern)
- **Notes**: The central DDL design decision: no parallel Mylar-style DDL_QUEUE/ddl_info world with hand-synced state.

#### Scenario: DDL grab honors the DownloadClient protocol

- **WHEN** a release is grabbed via the DDL client
- **THEN** the client returns a download id and exposes the same `get_items` / `remove` / status surface the SABnzbd client implements, and the grab appears in the shared tracked-download queue resource distinguishable from a SAB grab only by its protocol/client fields

#### Scenario: DDL failure feeds the standard failed pipeline

- **WHEN** a DDL download terminally fails
- **THEN** it enters the standard failed → blocklist → re-search loop identically to a failed SAB grab, with no DDL-private failure path

#### Scenario: Provenance source recorded as ddl

- **WHEN** a DDL grab is registered in the tracked-download state machine
- **THEN** its provenance is recorded with `source=ddl` so history and blocklist matching can distinguish it from usenet grabs

### Requirement: FRG-DDL-002 — GetComics search provider

The system SHALL implement a GetComics search provider that queries the site's search URL through an escalating query ladder (quoted exact "name #issue (year)", unquoted, name #issue, name year), following result pagination with a configurable depth cap, de-duplicating by post URL, skipping weekly-roundup posts, and emitting normalized release records into the standard decision engine.

- **Milestone**: M1
- **Source**: mylar-ddl §1.3, §1.4, §5 (query ladder, pagination, dedupe); mylar-ddl §3.7 (no pagination cap — fixed here)
- **Notes**: Deliberate divergence: Mylar stops at the first result passing its own filter; foragerr feeds all parsed candidates to the shared decision engine so DDL results compete with (and are explainable like) usenet results.

#### Scenario: Escalating query ladder with bounded pagination

- **WHEN** a wanted issue is searched and the exact "name #issue (year)" query returns no usable candidate
- **THEN** the provider escalates through the query ladder toward title-only, following the "older posts" pagination no deeper than the configured depth cap on each step

#### Scenario: Roundup and duplicate posts filtered

- **WHEN** search pages include a weekly-roundup post and the same post URL appears on two pages
- **THEN** the roundup post is skipped and the duplicate post URL is emitted only once

#### Scenario: Candidates feed the shared decision engine

- **WHEN** matching GetComics posts are parsed
- **THEN** each is emitted as a ReleaseCandidate carrying title, size, post date, post URL, and a quality tier derived from the page badges, and these candidates are ranked by the same shared change-4 decision engine and comparator that ranks Newznab releases — with no DDL-private quality notion

### Requirement: FRG-DDL-003 — Versioned page adapter with fixtures

All GetComics HTML parsing (search pages and post pages) SHALL live behind a versioned adapter with recorded HTML fixtures and tests, and unrecognized page structure SHALL fail gracefully (log, skip, provider health warning) rather than mis-parse or crash.

- **Milestone**: M1
- **Source**: mylar-ddl §3.1 (DOM coupling weakness), §5 (defensive adapter requirement)
- **Notes**: Also drop Mylar's cached-HTML-as-source-of-truth for retries; retries re-fetch the live post page (staleness bug in mylar-ddl §3.1).

#### Scenario: Parsing runs through adapter_v1 against committed fixtures

- **WHEN** the adapter parses a recorded search-result page and a recorded post page from the committed fixture corpus
- **THEN** parsing is performed by the versioned `adapter_v1` and yields the expected candidates and links, with the fixtures committed alongside the tests

#### Scenario: Selector miss raises typed AdapterDrift, never a crash

- **WHEN** a page whose structure no longer matches the adapter's selectors is fed to the adapter
- **THEN** the adapter raises a typed `AdapterDrift` error (not an unhandled exception), yields zero results, and the error is surfaced as a provider health warning rather than propagating as a crash

#### Scenario: Drift degrades provider health and engages back-off

- **WHEN** an `AdapterDrift` error is raised during a live search
- **THEN** the provider's health is marked degraded and the shared back-off ladder is engaged so the drifting provider is de-prioritized on subsequent searches

#### Scenario: Retries re-fetch the live post page

- **WHEN** a DDL item is retried after a failure
- **THEN** the post page is re-fetched live rather than re-parsed from a cached copy, so stale cached HTML cannot drive the retry

### Requirement: FRG-DDL-004 — Link enumeration and host/quality selection

For a chosen post, the system SHALL enumerate all offered download links keyed by quality tier (HD-Upscaled / HD-Digital / SD / normal) and host (main server, mirror, Mega, MediaFire, Pixeldrain), select one via a user-configurable host priority order and quality preference (default prefer upscaled), and SHALL reject known paywall/shortener links outright.

- **Milestone**: M1
- **Source**: mylar-ddl §1.5 (aio-pulse parsing, DDL_PRIORITY_ORDER, DDL_PREFER_UPSCALED, sh.st rejection); mylar-ddl §3.3 (table-driven rewrite of the copy-pasted ladder)
- **Notes**: Selection logic table-driven, not Mylar's 150-line if-ladder. Quality tier feeds the format/edition scoring in SRCH prioritization rather than a private notion of quality.

#### Scenario: Links enumerated per quality/host and ordered by configured priority

- **WHEN** a post offers download links across multiple quality sections and hosts
- **THEN** each per-quality/host section is parsed into candidate links, and the candidate list is ordered by the configurable host priority (default preferring upscaled quality) via a table-driven selection map

#### Scenario: Selection follows configured host order

- **WHEN** a post offers both a Mega link and a main-server link and the configured order prefers main server
- **THEN** the main-server link is selected as the first candidate and Mega is retained as the next-priority fallback

#### Scenario: Paywall and shortener hosts rejected at parse time

- **WHEN** a post contains an `sh.st` shortener or other known paywall host link
- **THEN** that link is rejected during parsing and never appears in the candidate list, so it is never fetched

### Requirement: FRG-DDL-005 — Per-host failover

On a download or verification failure, the system SHALL record the failed link type for the item and retry the same release via the next untried host per the priority order; only when all hosts are exhausted SHALL the item be marked Failed and handed to the standard failed-download pipeline (blocklist + re-search, issue state restored to wanted).

- **Milestone**: M1
- **Source**: mylar-ddl §1.7 (link_type_failure loop, reverse_the_pack_snatch); mylar-ddl §3.3 (GC_Mirror dispatch typo — the bug class to test against)
- **Notes**: Failover state lives on the persisted queue item; a dispatch-table test enumerates every link type to a handler (regression-proofing Mylar's typo bug).

#### Scenario: Failure advances to the next persisted host

- **WHEN** the currently selected host fails a download or verification and untried hosts remain on the item's persisted ordered link list
- **THEN** the failed link type is recorded on the queue row and the same release is retried via the next untried host per the priority order

#### Scenario: Host exhaustion hands off to the standard failed pipeline

- **WHEN** every host on the item's ordered link list has failed
- **THEN** the item is marked Failed and handed to the standard failed-download pipeline (blocklist the post, re-search, issue state restored to wanted)

#### Scenario: Dispatch table covers every link type

- **WHEN** the dispatch-table test enumerates every enumerable link type
- **THEN** each link type resolves to a concrete host handler with no unmapped or misspelled entry (regression-proofing Mylar's `GC_Mirror`/`GC-Mirror` typo)

### Requirement: FRG-DDL-006 — Politeness and provider self-protection

GetComics page fetches SHALL be rate-limited to a configurable minimum interval (default 15 s) plus random jitter with last-run/hit statistics persisted per provider, and the provider SHALL back off or self-disable (via the shared provider back-off ladder) on HTTP 429/503, Cloudflare challenge detection, and connection failures.

- **Milestone**: M1
- **Source**: mylar-ddl §1.8 (politeness summary), §3.7 (no jitter/backoff gaps), §5
- **Notes**: Reuses IDX's back-off ladder — one mechanism, all providers. Actual file downloads are not inter-delayed (matching Mylar's reasoning) but remain serialized (below).

#### Scenario: Page fetches respect the clamped minimum interval with jitter

- **WHEN** two consecutive GetComics page fetches occur
- **THEN** their timestamps are at least the configured minimum interval apart (default 15 s, clamped to configured bounds) with observable random jitter, and the per-provider last-run/hit statistics are persisted

#### Scenario: 429/503 escalates the shared back-off ladder

- **WHEN** a page fetch returns HTTP 429 or 503
- **THEN** the provider's `(provider_type, provider_id)` back-off ladder from change 4 is escalated and the provider is skipped by the next search until back-off clears

#### Scenario: Cloudflare challenge and connection failure trigger self-protection

- **WHEN** a Cloudflare challenge is detected or a connection failure occurs
- **THEN** the provider backs off or self-disables via the shared back-off ladder rather than retrying immediately

### Requirement: FRG-DDL-007 — Persistent serialized download queue

DDL downloads SHALL run from a database-backed queue whose items (status queued/downloading/completed/failed, progress, link/host, provenance) survive restart with in-flight items resuming or re-queueing automatically, executed single-flight (max concurrency 1, configurable), with manual retry, resume, abort, and remove actions.

- **Milestone**: M1
- **Source**: mylar-ddl §1.6 (DDL_LOCK, ddl_info), §3.2 (restart loses queue order — fixed), §5; mylar-ddl §1.7 (webserve retry/resume/abort)
- **Notes**: This queue is the DDL client's internal engine; its items are projected through get-items() into the common tracked-download view (no second user-facing queue).

#### Scenario: Serialized single-flight execution

- **WHEN** two items are queued in the ddl_queue with the default download pool of 1
- **THEN** they are processed in queue order and never download concurrently

#### Scenario: In-flight item survives restart via orphan recovery

- **WHEN** foragerr restarts while an item is downloading
- **THEN** SCHED orphan recovery leaves the persisted ddl_queue item queued/resumable without manual restore, preserving its status, progress, link/host, and provenance

#### Scenario: Manual queue actions available

- **WHEN** a user invokes retry, resume, abort, or remove on a ddl_queue item
- **THEN** the action is applied to the persisted item and reflected in the common tracked-download view

### Requirement: FRG-DDL-008 — Download execution and size accounting

File downloads SHALL stream with a sane chunk size (≥64 KiB), 30 s connect/read timeouts, record expected size (from the search result or Content-Length) and bytes received, and SHALL fail an attempt whose response lacks a usable Content-Length after retry or whose final size mismatches the expected size beyond tolerance (click-bait/ad-page detection).

- **Milestone**: M1
- **Source**: mylar-ddl §1.6 (downloadit), §3.4 (weak size model), §3.6 (1 KiB chunks)
- **Notes**: Expected-size check is the fix for Mylar's display-only use of the scraped size.

#### Scenario: Streaming to a staging partial with byte accounting

- **WHEN** a download runs
- **THEN** the response is streamed in chunks of at least 64 KiB into `<config>/ddl-staging/<id>.partial`, and bytes received are accounted against the expected size (search result or Content-Length)

#### Scenario: Missing Content-Length fails the attempt

- **WHEN** a response lacks a usable Content-Length after the retry
- **THEN** the attempt fails (triggering host failover) rather than being imported as a click-bait/ad page

#### Scenario: Size mismatch detected before import

- **WHEN** the final received byte count mismatches the expected size beyond tolerance
- **THEN** the attempt is marked failed rather than handed onward, catching truncated transfers

#### Scenario: Every hop egress-validated

- **WHEN** the downloader connects or follows a redirect hop
- **THEN** each hop is validated against the external egress profile before the request proceeds

### Requirement: FRG-DDL-009 — Safe resume by Range

Interrupted downloads SHALL resume by issuing a Range request from the local partial size, accepting the resume only when the server responds 206 with a Content-Range matching the requested offset; any other response (including 200 with full body) SHALL restart the download from zero, never appending.

- **Milestone**: M1
- **Source**: mylar-ddl §1.6 (DDL_AUTORESUME), §3.5 (resume trust flaw — fixed), §5
- **Notes**: Keeps Mylar's good idea, mandates the validation Mylar lacks.

#### Scenario: Valid 206 resume appends from the partial offset

- **WHEN** a `.partial` file exists and the server answers the Range request with 206 and a Content-Range whose offset matches the local partial size
- **THEN** the download resumes by appending from that offset and the completed file passes verification

#### Scenario: 200 full-body response forces a clean restart

- **WHEN** the server ignores the Range request and returns 200 with the full body
- **THEN** the downloader discards the partial and restarts from zero, never appending to the existing partial

#### Scenario: Content-Range mismatch forces a restart

- **WHEN** the server returns 206 but with a Content-Range offset that does not match the requested offset
- **THEN** the resume is rejected and the download restarts from zero

### Requirement: FRG-DDL-010 — Content verification before import

Every completed DDL file SHALL be verified before entering the import pipeline: magic-number check against the claimed type, full archive integrity (CRC) test for ZIP/RAR, and size sanity; verification failure SHALL count as a download failure (host failover, then failed handling).

- **Milestone**: M1
- **Source**: mylar-ddl §1.7 (check_file_condition), §4 (CRC does not authenticate — content checks needed), §5
- **Notes**: Deeper structural validation (cbz contains images) is the import pipeline's job (IMP area); this is the download-side gate.

#### Scenario: Magic bytes must match the extension

- **WHEN** a completed file is verified
- **THEN** its magic bytes are checked against the claimed extension (zip/rar/pdf), and a mismatch (e.g. an HTML error page named `.cbz`) counts as a download failure that triggers host failover

#### Scenario: CBZ opens as a zip with at least one image

- **WHEN** a completed `.cbz` file is verified
- **THEN** it must open as a valid zip containing at least one image entry (without extraction), and a file that fails to open or contains no images is rejected

#### Scenario: Size floor enforced

- **WHEN** a completed file falls below the minimum plausible size floor
- **THEN** verification fails and the item enters host failover, then standard failed handling if hosts are exhausted

### Requirement: FRG-DDL-011 — Safe filename generation

The system SHALL name downloaded files itself from library metadata and the queue id, sanitized for the target filesystem, and SHALL NOT derive filenames from redirect-final URLs or any other attacker-controllable remote value.

- **Milestone**: M1
- **Source**: mylar-ddl §4 (untrusted HTML → filesystem paths), §5
- **Notes**: Security-mandatory in the same change as the downloader (FRG-PROC-006); STRIDE entry required.

#### Scenario: Filename generated from library metadata

- **WHEN** a download's final filename is produced
- **THEN** it is system-generated as `{series} {issue} [__{issueid}__]{ext}` from library metadata and the queue id, built from safe path components sanitized for the target filesystem

#### Scenario: Remote-supplied names are never trusted

- **WHEN** a hostile redirect chain ends in a Content-Disposition header or final URL carrying a path-traversal-shaped name
- **THEN** the downloaded file still receives the locally generated safe name inside the DDL staging directory, and no remote/Content-Disposition-derived value influences the path

#### Scenario: Path-escape corpus is contained

- **WHEN** the path-escape test corpus of hostile remote names is exercised
- **THEN** every resulting file resolves to a safe name inside the DDL directory with no escape outside it

### Requirement: FRG-DDL-012 — Outbound URL security

All DDL HTTP fetches SHALL enforce a per-provider scheme and host allowlist, a capped redirect chain with each hop re-validated against the allowlist, TLS certificate verification always on (no `verify=False` anywhere, including any solver service), and session cookies SHALL never be sent to hosts outside the provider's allowlist.

- **Milestone**: M1
- **Source**: mylar-ddl §4 (blind redirects/SSRF, verify=False on FlareSolverr), §5
- **Notes**: Mirror hosts get added to the allowlist per host adapter. Mylar's per-provider proxy split-tunneling is not carried over; proxy support, if ever added, is process-wide (B).

#### Scenario: Off-allowlist redirect hop refused

- **WHEN** a scraped link or one of its redirect hops resolves to a host or scheme outside the provider allowlist, or to an internal address (SSRF probe)
- **THEN** the fetch is refused via the external egress profile, and the redirect chain is capped so it cannot be walked unbounded

#### Scenario: TLS verification is never disabled

- **WHEN** the codebase (including any solver-service integration) is inspected for outbound HTTP calls
- **THEN** no code path sets `verify=False` — TLS certificate verification is always on

#### Scenario: Session cookies confined to the allowlist

- **WHEN** a request is made to a host outside the provider's allowlist
- **THEN** provider session cookies are not attached, preventing session exfiltration

### Requirement: FRG-DDL-013 — Import handoff with provenance

Verified completed DDL downloads SHALL flow automatically into the standard import pipeline with provenance recorded (provider, post URL, selected host/link type, queue id) in history, and that provenance SHALL back DDL blocklist matching.

- **Milestone**: M1
- **Source**: mylar-ddl §5 (provenance requirement); sonarr-arch §4.3 (history data dict)
- **Notes**: Provenance replaces Mylar's `[__issueid__]` filename-tag hack for tying DDL files to issues — the download id join key does that job.

#### Scenario: Verified file enters import_pending automatically

- **WHEN** a DDL file passes verification
- **THEN** it is handed to the standard import pipeline as a `tracked_download` in `import_pending` state, with the issue id recovered from the `[__issueid__]` handshake tag and provenance (provider, post URL, selected host/link type, queue id) attached

#### Scenario: History records DDL provenance

- **WHEN** a DDL issue is imported
- **THEN** its history entry shows the GetComics post URL and the host/link type used, alongside the queue id

#### Scenario: Provenance backs blocklist matching

- **WHEN** a previously failed identical post is encountered again
- **THEN** the recorded provenance matches it as blocklisted and it is rejected before re-grabbing
