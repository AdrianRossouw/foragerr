# Tasks

## 1. Indexer providers (worktree area: indexers)

- [ ] 1.1 Migration: indexers, provider_backoff, release_cache tables; provider settings-contract registry with newznab implementation (SecretStr keys → redaction) (FRG-IDX-001, FRG-IDX-002)
- [ ] 1.2 Schema + test endpoints (`/api/v1/indexer/schema|test`, secrets write-only) with live caps probe and field-precise failures (FRG-IDX-003, FRG-API-009)
- [ ] 1.3 Caps probe with TTL cache, category selection (7030 fallback), degraded defaults recorded (FRG-IDX-004)
- [ ] 1.4 Tiered query generation (padded/volume/year variants via the sanitizing builder, per-tier caps, tier metadata) + offset/limit paging with hard cap (FRG-IDX-005)
- [ ] 1.5 defusedxml response parsing → ReleaseCandidate normalization + per-indexer guid dedup + attribution; `<error code>` → typed failures (FRG-IDX-006, FRG-IDX-007, FRG-SEC-002)
- [ ] 1.6 Per-indexer 2s asyncio gate; retention as maxage param (FRG-IDX-008, FRG-IDX-009)
- [ ] 1.7 Generic back-off ladder module keyed (provider_type, provider_id): escalation, Retry-After/auth fast-forward, success reset, skip+log, health surfacing (FRG-IDX-010, FRG-NFR-005)
- [ ] 1.8 Tagged tests incl. hostile-XML corpus (billion-laughs, external-entity, quadratic, oversized, junk), toggle gating, spacing, ladder persistence across restart (FRG-IDX-001..010, FRG-SEC-002, FRG-NFR-005)

## 2. Decision engine (worktree area: search-engine)

- [ ] 2.1 Engine core: ordered all-run specs, Decision outcomes, full reason lists (FRG-SRCH-001)
- [ ] 2.2 Parser-contract spec (failure → rejection, never exception) + release-to-library mapping (matching key + aliases, year/volume disambiguation, distinct unknown-series/issue reasons) (FRG-SRCH-002, FRG-SRCH-003)
- [ ] 2.3 Core spec set: format-allowed, upgrade-allowed vs cutoff, retention, min-age (Temporary), must/must-not terms, queue/blocklist stubs (empty until change 5), free-space (FRG-SRCH-004)
- [ ] 2.4 Search-match specs with adversarial fixtures (substring series, year-in-title) (FRG-SRCH-006)
- [ ] 2.5 Comparator chain with log/step bucketing; property test for total deterministic order (FRG-SRCH-007)
- [ ] 2.6 Cross-indexer dedup (normalized title + size bucket, higher-priority wins) (FRG-SRCH-010)
- [ ] 2.7 Tagged tests: decision matrix per spec, engine-never-crashes sweep over hostile titles (FRG-SRCH-001..004, 006, 007, 010)

## 3. Search commands + release API (worktree area: search-api)

- [ ] 3.1 IssueSearch/SeriesSearch commands (search pool, replaces change-3 stub) → engine → comparator → recorded grab handoff (inert) (FRG-SRCH-008)
- [ ] 3.2 Scheduled backlog search: oldest-first walk, clamped inter-search delay, back-off skip, restart-safe (FRG-SRCH-009)
- [ ] 3.3 `GET /api/v1/release?issueId=` (all decisions + reasons, comparator-sorted, cache keys) + cache table with housekeeping prune; `POST /api/v1/release` cache-hit grab command / expiry → deterministic 404-class error (FRG-SRCH-014, FRG-API-008)
- [ ] 3.4 Misbehaving-provider end-to-end: hang/drip/junk/429-storm fixture server cannot wedge the search pool; healthy indexers complete in the same command (FRG-NFR-010)
- [ ] 3.5 Tagged tests for 3.1-3.4 (FRG-SRCH-008, FRG-SRCH-009, FRG-SRCH-014, FRG-API-008, FRG-NFR-010)

## 4. Security docs, traceability, merge gate

- [ ] 4.1 Risk register: RISK-024/035 → mitigated-by FRG-SEC-002; RISK-027 → FRG-NFR-005/010; threat-model delta for the indexer integration (FRG-PROC-006)
- [ ] 4.2 Every in-scope id tagged-tested; flip 25 registry rows; trace.py exit 0 (FRG-PROC-004, FRG-PROC-005)
- [ ] 4.3 Suite green → /code-review → /simplify → merge --no-ff → archive → decision-index update (FRG-PROC-007)
