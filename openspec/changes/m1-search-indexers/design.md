# Design: m1-search-indexers

## Context

Builds on changes 1-3: HTTP factory (`external` profile), command backbone, library
domain with format profiles, parser with the pinned SRCH-002 contract. Sonarr's
decision-engine shape (sonarr-architecture.md §2-3) is the blueprint; comics
constraints (q=-only searching, category 7030) come from the Mylar research. The
back-off ladder built here is deliberately generic — change 5's download clients and
DDL provider reuse it unmodified (FRG-IDX-010 ↔ FRG-DDL-006).

## Goals / Non-Goals

**Goals:** configured indexers searchable end-to-end: automatic + scheduled backlog +
interactive search produce decisions with visible reasons; approved candidates
prioritized; grab cached — everything short of actually downloading.

**Non-Goals:** grab execution (change 5), RSS sync (B), Torznab (M2), preferred-term
scoring/size bounds (M2), UI (change 7).

## Decisions

1. **Provider pattern** (`indexers/`): `indexers` table (id, name, implementation,
   settings JSON, enable_rss/enable_auto/enable_interactive, priority, retention
   override). Implementations register a Pydantic settings contract; `newznab` is the
   only M1 implementation. `GET /api/v1/indexer/schema` returns field metadata
   (name/type/label/help/required/secret) derived from the contract — the
   zero-frontend seam; `POST /api/v1/indexer/test` runs the caps probe live and maps
   failures to field-precise messages (FRG-IDX-003, API-009).

2. **Caps probe** (FRG-IDX-004): `?t=caps` on save/test; cached per indexer with TTL;
   drives category selection (7030 comics with fallback) and search-mode support
   flags; a failed probe degrades to conservative defaults, recorded on the row.

3. **Query generation** (FRG-IDX-005): tiered `q=` ladder from the cleaned series
   title (shared normalization) + issue variants — padded (007/07/7), volume-tagged,
   year-tagged — descending specificity; per-tier result cap; queries built only via
   the change-3 sanitizing query builder (CV-derived text never raw). Tier metadata
   attached to results for the comparator (more specific tier → higher confidence).

4. **Hardened parsing** (FRG-IDX-006 + SEC-002): defusedxml.ElementTree everywhere;
   DTD/external entities/expansion disabled; parse under the factory's byte cap;
   `<error code>` → typed failures (auth/limit/malformed/unavailable) feeding the
   back-off ladder; malformed items skipped with counts, never crashing the batch.
   Hostile corpus: billion-laughs, external-entity, quadratic-blowup, oversized, junk.

5. **Normalized releases** (FRG-IDX-007): `ReleaseCandidate` dataclass (guid, title,
   link, size, pubdate, indexer id/name, tier, categories, attributes) — per-indexer
   guid dedup at parse; cross-indexer dedup in SRCH (FRG-SRCH-010) by normalized
   title+size bucket, keeping the higher-priority indexer's copy.

6. **Back-off ladder** (FRG-IDX-010 + NFR-005, generic module `providers/backoff.py`):
   persisted per-provider state (failure count, level, next_allowed_at) with
   escalation 1m→5m→15m→1h→3h→6h→12h→24h, fast-forward on Retry-After/auth failures,
   full reset on success, honored by every fetch path (skip + log when backing off).
   Keyed (provider_type, provider_id) so DL/DDL reuse it in change 5 without schema
   change. Per-indexer 2s request spacing (FRG-IDX-008) as an asyncio gate per row.

7. **Decision engine** (`search/engine.py`, FRG-SRCH-001): ordered spec list, each
   `evaluate(candidate, context) -> Decision(accept | reject(reason, Permanent |
   Temporary))`; ALL specs run (full reason list, not first-fail); result =
   Approved / Rejected / TemporarilyRejected. Context carries series, issue, profile,
   wanted-state, queue/blocklist lookups (change-5 stubs return empty). M1 spec
   inventory (FRG-SRCH-004/006): parse-ok (SRCH-002 contract: parser failure reason →
   rejection), series-match (mapping via matching key + aliases, FRG-SRCH-003),
   issue-match, year-sanity, format-allowed + upgrade-allowed (profile), retention
   (FRG-IDX-009), already-queued stub, blocklist stub. Each spec one class, one test
   file, reasons user-renderable strings.

8. **Comparator chain** (FRG-SRCH-007): format rung → indexer priority → query-tier
   specificity → bucketed age → size closeness to profile midpoint (log bucketing per
   Sonarr). Pure function over approved candidates; property test: total order.

9. **Search commands** (FRG-SRCH-008/009): `IssueSearchCommand` /
   `SeriesSearchCommand` (replaces change-3 inert stub) on the `search` pool
   (size 1 = serialized politeness); scheduled `BacklogSearchCommand` walks wanted
   issues oldest-first with per-issue inter-search delay (config, clamped ≥ politeness
   floor), stopping at the ladder's backing-off indexers; results → engine →
   approved+prioritized → grab handoff (inert until change 5, recorded in history).

10. **Interactive search + grab cache** (FRG-SRCH-014 + API-008):
    `GET /api/v1/release?issueId=` runs a fresh multi-indexer search, returns ALL
    decisions (approved + rejected with reasons) sorted by the comparator; each row
    carries a cache key (indexerId+guid); results cached server-side ~30 min (table
    with expiry, pruned by housekeeping). `POST /api/v1/release {indexerId, guid}`
    resolves from cache — hit → enqueue grab command (inert in this change) — miss/
    expired → 404-class uniform error, never a silent re-search.

11. **Wiring**: indexer fetches use `external` clients; per-indexer API keys are
    SecretStr settings fields in the JSON contract, registered for redaction at row
    load; NFR-010 acceptance = a hostile indexer (hang/drip/junk) cannot wedge the
    search worker (timeouts + byte caps + ladder), asserted by an end-to-end test
    with a misbehaving fixture server.

## Risks / Trade-offs

- [q=-only searching yields wrong-series hits] → search-match specs are load-bearing;
  corpus of adversarial title fixtures (substring series, year-in-title) pins them.
- [Back-off state contention with change 5 consumers] → keyed generic table + module
  API from day one; DL/DDL add rows, not schema.
- [Grab cache growth] → expiry + housekeeping prune; cap rows per issue.
- [Engine perf over many candidates] → specs are pure/sync over in-memory candidates;
  fine at M1 scale (≤ result caps).

## Migration Plan

One forward migration: indexers, provider_backoff, release_cache tables. Rollback =
don't merge.

## Open Questions

None blocking.
