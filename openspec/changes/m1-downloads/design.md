# Design: m1-downloads

## Context

Builds on changes 1-4: command backbone (download pool = 1), HTTP factory
(`local-service` profile for SABnzbd, `external` for NZB fetch + DDL), decision
engine with cached grab (change 4's inert grab command goes live here), the generic
back-off ladder, and the parser (`[__issueid__]` handshake, re-parse fallback).
Sonarr's download pipeline (sonarr-architecture.md §4) is the blueprint; DDL behavior
comes from mylar-ddl.md with its defect catalog as the anti-spec.

## Goals / Non-Goals

**Goals:** approved releases actually download via SABnzbd or the built-in DDL
client; every download is tracked to "awaiting import" (or failed → blocklisted →
re-searched); the queue endpoint reflects tracked state only.

**Non-Goals:** import execution + client cleanup (change 6: FRG-DL-009/010), SAB
retry passthrough (B), packs/extraction/Cloudflare/mirrors (B), torrents (M2), UI (7).

## Decisions

1. **Client abstraction** (`downloads/clients/base.py`, FRG-DL-001/002):
   `DownloadClient` protocol — `test()`, `download(release) -> download_id`,
   `get_items() -> list[ClientItem]`, `remove(id, delete_data)`, `mark_imported(id)`.
   `download_clients` table mirrors the indexer provider pattern (implementation,
   settings JSON contract, enable flag, priority, schema/test endpoints reuse the
   change-4 provider API machinery generically — `/api/v1/downloadclient/schema|test`).
   Grab command: pick enabled client matching the release protocol (usenet → SAB,
   ddl → built-in); client unreachable at grab → command fails with typed error,
   release cache entry stays valid, grab retryable — never silently dropped.

2. **SABnzbd** (FRG-DL-003..005): `local-service` egress profile on the operator
   base URL; API key SecretStr redacted. Grab: fetch NZB bytes via `external`
   profile from the indexer link (through indexer back-off ladder), validate
   (non-empty, parses as XML with defusedxml, contains ≥1 file segment), upload via
   `mode=addfile` (multipart) with category from settings; store returned nzo_id as
   download_id. Polling: `mode=queue` + `mode=history` mapped to typed
   `ClientItem(status ∈ queued/downloading/paused/completed/failed/encrypted,
   remote_path, progress, size)`; encrypted/pw-protected history entries map to
   failed with reason. Remote path mapping table (client host + remote prefix →
   local prefix) applied to completed paths (FRG-DL-005/FRG-PP-008 share the
   mechanism; PP re-uses in change 6).

3. **Grab history + tracking** (FRG-DL-006..008): `grab_history` row at grab time
   (download_id, issue_id, release title/guid/indexer, size, provenance
   source=indexer|ddl) — the join key. `TrackDownloadsCommand` on the scheduler
   (~1 min, download pool): fetch items from every enabled client, match by
   download_id to grab_history; unmatched items → re-parse client item title via the
   parser (issue-id tag wins if present) and adopt or mark unknown. State machine
   `tracked_downloads.state`: grabbed → downloading → import_pending (completed,
   awaiting change-6 pipeline) | failed | ignored. Transitions emit events; state
   persisted; restart-safe. `GET /api/v1/queue` (FRG-API-007): paged envelope over
   tracked_downloads joined to series/issues — never a live client call.

4. **Failure loop** (FRG-DL-011..013): client-reported failed / encrypted /
   vanished-before-completion → state failed → `blocklist` row (multi-field: guid,
   indexer id, title, size, download_id, source) → `IssueSearchCommand` enqueued
   automatically (dedup protects against storms) → change 4's
   BlocklistSpecification + already-queued spec now evaluate live stores.
   Manual queue remove: `DELETE /api/v1/queue/{id}?blocklist=true|false`.

5. **DDL provider** (`ddl/`, FRG-DDL-002..006): GetComics search provider registered
   as a change-4 search provider (indexer-like row, `ddl` protocol): escalating
   query ladder (title+issue → title only), bounded pagination, roundup-page
   skipping; results normalized to ReleaseCandidates (protocol ddl, quality tier
   from page badges) feeding the SAME decision engine. All HTML parsing behind
   `ddl/adapter_v1.py` — versioned, fixture-backed (recorded pages committed);
   selector misses → typed AdapterDrift error → provider health degraded + ladder
   back-off, never a crash. Page fetches ≥15s apart (politeness config, clamped),
   through `external` egress profile. Link enumeration: per-quality/host sections
   parsed into candidate links ordered by configurable host priority; paywall/
   shortener hosts rejected at parse.

6. **DDL execution** (FRG-DDL-007..013): `ddl_queue` table (persistent, serialized
   — download pool 1; restart-surviving via SCHED orphan recovery). Download:
   streaming to `<config>/ddl-staging/<id>.partial` with byte-count accounting
   against Content-Length (mismatch → failed); every hop egress-validated; safe
   filename = system-generated `{series} {issue} [__{issueid}__]{ext}` via
   safe_path_component (never remote-derived, FRG-DDL-011). Resume: on restart with
   a `.partial`, send Range; validate 206 + Content-Range offset before appending —
   200/mismatch → restart from zero (FRG-DDL-009). Per-host failover: link list on
   the queue row; host failure → next host via dispatch table, exhausted → standard
   failed pipeline (FRG-DDL-005). Verification before handoff (FRG-DDL-010): magic
   bytes match extension (zip/rar/pdf), size > floor, cbz opens as zip with ≥1
   image entry (stdlib zipfile — no extraction); failure → failed pipeline.
   Success → tracked_download state import_pending with provenance
   source=ddl + issue id from the handshake tag (FRG-DDL-013/001).

7. **Testing**: SAB contract tests against a recorded fixture API (queue/history
   JSON shapes incl. encrypted + weird paths); DDL adapter fixtures = committed
   recorded GetComics pages (search results, article, links section, roundup,
   drifted layout); download execution against local fixture servers (Range
   honored/ignored, drip, wrong Content-Length, redirect-to-private); state-machine
   matrix tests; failure-loop end-to-end (failed → blocklist row → re-search command
   enqueued → blocklist spec rejects same guid).

## Risks / Trade-offs

- [GetComics layout drift breaks the adapter] → versioned adapter + fixtures +
  typed drift error degrading to back-off; drift updates are a fixture refresh, not
  a code archaeology dig.
- [SAB path semantics vary by host] → remote path mapping table + treat unmapped
  completed paths as import-blocked (change 6 surfaces them), never guessed.
- [DL-009/010 deferral leaves items parked] → explicit `import_pending` state
  visible in queue; change 6 drains it — no silent loss.
- [Range resume against dishonest hosts] → strict 206/Content-Range validation,
  fall back to full restart; corrupted-tail risk covered by content verification.

## Migration Plan

One forward migration: download_clients, grab_history, tracked_downloads,
blocklist, remote_path_mappings, ddl_queue. Rollback = don't merge.

## Open Questions

None blocking.
