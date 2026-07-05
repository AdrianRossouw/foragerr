# Tasks

## 1. Client abstraction + SABnzbd (worktree area: downloads)

- [x] 1.1 Migration: download_clients, grab_history, tracked_downloads, blocklist, remote_path_mappings, ddl_queue; DownloadClient protocol + provider rows with schema/test endpoints (generic reuse of the change-4 provider machinery) (FRG-DL-001, FRG-DL-002)
- [x] 1.2 SABnzbd client: local-service profile; server-side NZB fetch (external profile, ladder) + defusedxml validation + mode=addfile; queue/history polling → typed ClientItem states incl. encrypted; version/config checks in test action (FRG-DL-003, FRG-DL-004)
- [x] 1.3 Remote path mapping table + application to completed paths with check-mapping warning (FRG-DL-005)
- [x] 1.4 Tagged tests on recorded SAB fixtures: state mapping matrix, encrypted, addfile round-trip, unreachable-client retryable grab, mapping rewrites (FRG-DL-001..005)
- [x] 1.5 SAB container integration layer (docker-gated marker, runs at the change gate + in change 8): spin up linuxserver/sabnzbd, exercise the live API contract — auth, mode=addfile → real nzo_id, queue/history shapes, category filtering, delete, get_config/version in the test action — and regenerate the recorded fixtures from its responses so fixture drift is bounded; download completion is exercised for real when news-server credentials are present: an env-gated tier (creds from .env — Tweaknews/Newshosting, never logged or committed) configures the SAB container's news servers and completes ONE small test download end-to-end (grab → SAB fetch → completed → import_pending), keeping usage minimal and polite; without creds this tier skips and completion stays fixture-based, with SAB's fetch-failure states exercised as real failure input (FRG-DL-003, FRG-DL-004)

## 2. Tracking + failure loop (worktree area: tracking)

- [x] 2.1 grab_history writes at grab (per-issue rows, provenance); live grab command replaces change-4 inert handoff (FRG-DL-006)
- [x] 2.2 TrackDownloadsCommand (~1 min + event-triggered): id-match, parser fallback with issue-id tag priority, state machine with persisted transitions + events (FRG-DL-007)
- [x] 2.3 GET /api/v1/queue paged from tracked state (never live client calls) + DELETE with blocklist option (FRG-DL-008, FRG-API-007)
- [x] 2.4 Failed handling → multi-field blocklist rows → automatic IssueSearchCommand with dedup guards; wire change-4 queue/blocklist specs to live stores (FRG-DL-011, FRG-DL-012, FRG-DL-013)
- [x] 2.5 Tagged tests: state-machine matrix, restart safety, queue-within-one-cycle, failure loop end-to-end (failed → blocklist → re-search → different release), storm dedup (FRG-DL-006..008, 011..013)

## 3. DDL provider + execution (worktree area: ddl)

- [ ] 3.1 GetComics search provider: query ladder, bounded pagination, roundup skip, URL dedup, ReleaseCandidates into the shared engine (FRG-DDL-002)
- [ ] 3.2 adapter_v1 with committed page fixtures; AdapterDrift typed error → health + ladder; live re-fetch on retry (FRG-DDL-003)
- [ ] 3.3 Link enumeration (quality/host table-driven, paywall rejection) + per-host failover with full dispatch-table test (FRG-DDL-004, FRG-DDL-005)
- [ ] 3.4 Politeness: ≥15s jittered page fetches, persisted stats, ladder reuse on 429/503/Cloudflare (FRG-DDL-006)
- [ ] 3.5 ddl_queue engine: persisted single-flight processing, restart orphan recovery, retry/resume/abort/remove actions, projection through get_items() (FRG-DDL-001, FRG-DDL-007)
- [ ] 3.6 Execution: streaming + byte accounting, Range resume with strict 206/Content-Range validation, per-hop egress, magic/size/zip verification, safe system-generated filenames with [__issueid__] tag, import_pending handoff with provenance (FRG-DDL-008..013)
- [ ] 3.7 Tagged tests: fixture servers (Range honored/ignored/mismatched, drip, wrong Content-Length, redirect-to-private, hostile Content-Disposition), verification corpus, failover exhaustion → failed pipeline (FRG-DDL-001..013)

## 4. Security docs, traceability, merge gate

- [ ] 4.1 Risk register: RISK-007/008/009 (DDL SSRF/hostile content), RISK-029 (SAB paths) → mitigation status; STRIDE delta for SAB + DDL surfaces (FRG-PROC-006)
- [ ] 4.2 All 25 ids tagged-tested; registry flip; trace.py exit 0 (FRG-PROC-004, FRG-PROC-005)
- [ ] 4.3 Suite green → /code-review → /simplify → merge --no-ff → archive → decision-index update (FRG-PROC-007)
