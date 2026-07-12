# Requirements Registry

The authoritative allocation table for requirement IDs (**FRG-PROC-002**). An ID is
allocated here at the moment its requirement first appears in an OpenSpec change
proposal, and is never reused or renumbered — including for withdrawn requirements,
which are marked `withdrawn` but keep their row.

The commit-msg hook rejects any commit whose `Refs:` trailer cites an ID not listed here.

Status: `proposed` (in an open change) → `approved` (baseline approved by owner) →
`implemented` (code + tagged tests merged) → `verified` (tests green in CI).
Also: `deferred` (approved, explicitly parked), `withdrawn` (kept for history).

Milestones: `M1` vertical slice · `M2` own your library · `M3` comics-native
(closed 2026-07-10 by rescoping the pull experience to M4; shipped: pull
backbone, volume grouping, trade typing, OPDS page streaming) · `M4` design
refresh (new app shell/tokens, library views, series detail + trade
containment, add-new, the pull experience [FRG-UI-018, FRG-PULL-007..009],
screenshot-refresh tooling) · `M5` creators & follows (CRTR ids allocated at
proposal time; closed 2026-07-11, shipped v0.5.0–v0.5.5) · `M6` sources
(FRG-AUTH-008 credential store first, then Humble Bundle importer +
companion extension) · `M7` torrents (post-1.0; label kept — ids are never
renumbered) · `M8` authentication (**implementation requires fresh owner
approval**) · `M9` UI refinement · `M10` go-live, ends in the 1.0 release ·
`B` backlog · `—` process (not milestone-bound).

Reshaped 2026-07-05 with owner approval (previously: `M2` torrents + streaming,
`M3` authentication). Torrents (FRG-TOR-*, FRG-IDX-012) and notifications
(FRG-NOTIF-*, FRG-UI-013) parked to `B`; PULL area and FRG-UI-018 promoted from
`B` to `M3`; auth cluster (FRG-AUTH-002..010, FRG-SEC-005) moved to `M5`.

Reshaped again 2026-07-10 with owner approval (roadmap-reshape): FRG-UI-018 +
FRG-PULL-007..009 moved `M3`→`M4`; FRG-AUTH-008 moved `M5`→`M6` (sources
store real account credentials); FRG-TOR-001..006 + FRG-IDX-012 promoted
`B`→`M7`; remaining auth cluster (FRG-AUTH-002..007/009/010, FRG-SEC-005)
moved `M5`→`M8`.

1.0 cut decided 2026-07-11 with owner approval (recorded at the M6 kickoff,
2026-07-12): 1.0 = M6 → M8 → M9 (UI refinement, new) → M10 (go-live, new).
Torrents move past 1.0 in sequence; `M7` rows keep their milestone label and
no id is renumbered. The archive.org importer leaves M6 — when picked up
post-1.0 it is shaped as an indexer + direct-download capability, not a store
source. Compatibility: pre-1.0 releases may break with migration notes; from
1.0, strict SemVer on public surfaces (REST, OPDS, config, env vars).

| ID | Title | Spec | Status | Milestone |
|----|-------|------|--------|-----------|
| FRG-PROC-001 | Commit traceability: Conventional Commits + Refs trailer | dev-process | active | — |
| FRG-PROC-002 | Stable, registered requirement identifiers | dev-process | active | — |
| FRG-PROC-003 | Spec before code (OpenSpec change workflow) | dev-process | active | — |
| FRG-PROC-004 | Every requirement verified by tagged automated tests | dev-process | active | — |
| FRG-PROC-005 | Maintained traceability matrix | dev-process | active | — |
| FRG-PROC-006 | Threat analysis and living risk register | dev-process | active | — |
| FRG-PROC-007 | Branch-based integration, green main | dev-process | active | — |
| FRG-PROC-008 | Worktree isolation for concurrent agents | dev-process | active | — |
| FRG-PROC-009 | Spec approval gate | dev-process | active | — |
| FRG-PROC-010 | End-to-end slice verification harness | dev-process | implemented | M1 |
| FRG-PROC-011 | Manual kept in sync with the application | dev-process | active | — |
| FRG-PROC-012 | SOUP register | dev-process | active | — |
| FRG-PROC-013 | Release tagging | dev-process | active | — |
| FRG-PROC-014 | Public repository labelling and posture | dev-process | active | — |
| FRG-PROC-015 | Repository history hygiene | dev-process | active | — |
| FRG-PROC-016 | Known-anomalies register | dev-process | active | — |
| FRG-PROC-017 | Regenerable README screenshots | dev-process | implemented | M4 |
| FRG-PROC-018 | Roadmap single source of truth | dev-process | implemented | M4 |
| FRG-SER-001 | Series entity from ComicVine volume | ser | implemented | M1 |
| FRG-SER-002 | Issue entity | ser | implemented | M1 |
| FRG-SER-003 | Two-level monitored flags | ser | implemented | M1 |
| FRG-SER-004 | Derived wanted state | ser | implemented | M1 |
| FRG-SER-005 | Add flow (add → refresh → scan → optional search) | ser | implemented | M1 |
| FRG-SER-006 | Add-time monitoring strategies | ser | implemented | M1 |
| FRG-SER-007 | Monitor-new-items policy | ser | implemented | M1 |
| FRG-SER-008 | Root folders and series paths | ser | implemented | M1 |
| FRG-SER-009 | Series statistics | ser | implemented | M1 |
| FRG-SER-010 | Per-series disk rescan | ser | implemented | M1 |
| FRG-SER-011 | Annuals and specials as typed issues | ser | approved | B |
| FRG-SER-012 | Continuing/Ended status maintenance | ser | approved | B |
| FRG-SER-013 | Per-series overrides survive refresh | ser | approved | B |
| FRG-SER-014 | Series edit and delete | ser | implemented | M1 |
| FRG-SER-015 | Bulk series operations | ser | approved | B |
| FRG-SER-016 | Volume grouping model and franchise derivation | ser | implemented | M3 |
| FRG-SER-017 | Grouping manual override survives refresh | ser | implemented | M3 |
| FRG-SER-018 | Series collected-edition (trade) typing | ser | implemented | M3 |
| FRG-SER-019 | Trades never suppress single-issue wanted | ser | implemented | M3 |
| FRG-SER-020 | Trade containment model (declared, display-only) | ser | implemented | M4 |
| FRG-META-001 | ComicVine client fundamentals | meta | implemented | M1 |
| FRG-META-002 | API key handling | meta | implemented | M1 |
| FRG-META-003 | Client-side rate limiting with 429 handling | meta | implemented | M1 |
| FRG-META-004 | Pagination with partial-failure tolerance | meta | implemented | M1 |
| FRG-META-005 | Volume-to-series mapping | meta | implemented | M1 |
| FRG-META-006 | Issue mapping | meta | implemented | M1 |
| FRG-META-007 | Series search | meta | implemented | M1 |
| FRG-META-008 | Refresh reconciliation (Sonarr model) | meta | implemented | M1 |
| FRG-META-009 | Scheduled refresh with staleness rules | meta | approved | B |
| FRG-META-010 | Incremental changed-since sync | meta | approved | B |
| FRG-META-011 | Volume identity-change guard | meta | approved | B |
| FRG-META-012 | Heuristic fields with provenance and override | meta | approved | B |
| FRG-META-013 | Cover art download and cache | meta | implemented | M1 |
| FRG-META-014 | ComicVine content is untrusted input | meta | implemented | M1 |
| FRG-META-015 | Relevance ordering of lookup candidates | meta | implemented | M4 |
| FRG-PULL-001 | Metadata-derived weekly release view | pull | implemented | M3 |
| FRG-PULL-002 | External pull-source fetch | pull | implemented | M3 |
| FRG-PULL-003 | Idempotent per-week storage | pull | implemented | M3 |
| FRG-PULL-004 | Matching pull entries to the library | pull | implemented | M3 |
| FRG-PULL-005 | Refresh trigger for missing pulled issues | pull | implemented | M3 |
| FRG-PULL-006 | Scheduled and manual pull refresh | pull | implemented | M3 |
| FRG-PULL-007 | Pull view actions | pull | implemented | M4 |
| FRG-PULL-008 | New-series surfacing (no auto-add) | pull | implemented | M4 |
| FRG-PULL-009 | Future/solicited releases | pull | implemented | M4 |
| FRG-CRTR-001 | Per-issue creator credits ingest | crtr | implemented | M5 |
| FRG-CRTR-002 | Creator and credit storage/reconciliation | crtr | implemented | M5 |
| FRG-CRTR-003 | One-time credits backfill | crtr | implemented | M5 |
| FRG-CRTR-004 | Creator follow flag (explicit-only) | crtr | implemented | M5 |
| FRG-CRTR-005 | External creator bibliography fetch and cache | crtr | implemented | M5 |
| FRG-ARC-001 | Arc entity import by ComicVine arc ID | arc | approved | B |
| FRG-ARC-002 | Arc-to-library linking by ComicVine ID | arc | approved | B |
| FRG-ARC-003 | Arc progress | arc | approved | B |
| FRG-ARC-004 | Wanting missing arc issues | arc | approved | B |
| FRG-ARC-005 | Add missing series from arc | arc | approved | B |
| FRG-ARC-006 | Arc refresh reconciliation | arc | approved | B |
| FRG-ARC-007 | Reading-order editing and manual members | arc | approved | B |
| FRG-ARC-008 | CBL reading-list import | arc | approved | B |
| FRG-ARC-009 | Arc directory materialization | arc | approved | B |
| FRG-ARC-010 | Arcs in OPDS (boundary requirement) | arc | approved | B |
| FRG-IDX-001 | Indexer configuration model | idx | implemented | M1 |
| FRG-IDX-002 | Per-indexer usage toggles | idx | implemented | M1 |
| FRG-IDX-003 | Connectivity test and dynamic settings schema | idx | implemented | M1 |
| FRG-IDX-004 | Newznab capabilities probe | idx | implemented | M1 |
| FRG-IDX-005 | Newznab query generation | idx | implemented | M1 |
| FRG-IDX-006 | Newznab response parsing and error mapping | idx | implemented | M1 |
| FRG-IDX-007 | Release normalization and de-duplication | idx | implemented | M1 |
| FRG-IDX-008 | Per-indexer request rate limiting | idx | implemented | M1 |
| FRG-IDX-009 | Usenet retention parameter | idx | implemented | M1 |
| FRG-IDX-010 | Indexer failure back-off and recovery | idx | implemented | M1 |
| FRG-IDX-011 | RSS gap detection | idx | approved | B |
| FRG-IDX-012 | Torznab indexer support | idx | approved | M7 |
| FRG-SRCH-001 | Unified decision engine with explainable rejections | srch | implemented | M1 |
| FRG-SRCH-002 | Release title parsing | srch | implemented | M1 |
| FRG-SRCH-003 | Release-to-library mapping | srch | implemented | M1 |
| FRG-SRCH-004 | Core specification set | srch | implemented | M1 |
| FRG-SRCH-005 | RSS-mode specifications | srch | approved | B |
| FRG-SRCH-006 | Search-match specifications | srch | implemented | M1 |
| FRG-SRCH-007 | Prioritization comparator chain | srch | implemented | M1 |
| FRG-SRCH-008 | Automatic search commands | srch | implemented | M1 |
| FRG-SRCH-009 | Scheduled backlog search with politeness | srch | implemented | M1 |
| FRG-SRCH-010 | Search result de-duplication | srch | implemented | M1 |
| FRG-SRCH-011 | RSS sync | srch | approved | B |
| FRG-SRCH-012 | Delay profile | srch | approved | B |
| FRG-SRCH-013 | Pending release queue | srch | approved | B |
| FRG-SRCH-014 | Interactive search | srch | implemented | M1 |
| FRG-DL-001 | Download client abstraction | dl | implemented | M1 |
| FRG-DL-002 | Client configuration and selection | dl | implemented | M1 |
| FRG-DL-003 | SABnzbd add via file upload | dl | implemented | M1 |
| FRG-DL-004 | SABnzbd queue and history polling | dl | implemented | M1 |
| FRG-DL-005 | Remote path mapping | dl | implemented | M1 |
| FRG-DL-006 | Grab history with download-id join key | dl | implemented | M1 |
| FRG-DL-007 | Tracked-download state machine | dl | implemented | M1 |
| FRG-DL-008 | Queue view from tracked downloads | dl | implemented | M1 |
| FRG-DL-009 | Completed download handling | dl | implemented | M1 |
| FRG-DL-010 | Post-import client cleanup | dl | implemented | M1 |
| FRG-DL-011 | Failed download handling | dl | implemented | M1 |
| FRG-DL-012 | Blocklist | dl | implemented | M1 |
| FRG-DL-013 | Automatic re-search after failure | dl | implemented | M1 |
| FRG-DL-014 | SABnzbd retry passthrough | dl | approved | B |
| FRG-DDL-001 | DDL client behind the common abstraction | ddl | implemented | M1 |
| FRG-DDL-002 | GetComics search provider | ddl | implemented | M1 |
| FRG-DDL-003 | Versioned page adapter with fixtures | ddl | implemented | M1 |
| FRG-DDL-004 | Link enumeration and host/quality selection | ddl | implemented | M1 |
| FRG-DDL-005 | Per-host failover | ddl | implemented | M1 |
| FRG-DDL-006 | Politeness and provider self-protection | ddl | implemented | M1 |
| FRG-DDL-007 | Persistent serialized download queue | ddl | implemented | M1 |
| FRG-DDL-008 | Download execution and size accounting | ddl | implemented | M1 |
| FRG-DDL-009 | Safe resume by Range | ddl | implemented | M1 |
| FRG-DDL-010 | Content verification before import | ddl | implemented | M1 |
| FRG-DDL-011 | Safe filename generation | ddl | implemented | M1 |
| FRG-DDL-012 | Outbound URL security | ddl | implemented | M1 |
| FRG-DDL-013 | Import handoff with provenance | ddl | implemented | M1 |
| FRG-DDL-014 | Pack and booktype recognition | ddl | approved | B |
| FRG-DDL-015 | Safe archive extraction | ddl | approved | B |
| FRG-DDL-016 | Cloudflare session handling | ddl | approved | B |
| FRG-DDL-017 | Mirror host adapters | ddl | approved | B |
| FRG-TOR-001 | Torrent as a second protocol | tor | approved | M7 |
| FRG-TOR-002 | qBittorrent client | tor | approved | M7 |
| FRG-TOR-003 | Magnet and .torrent handling | tor | approved | M7 |
| FRG-TOR-004 | Seeding-aware import and removal | tor | approved | M7 |
| FRG-TOR-005 | Seeder-based decision and prioritization | tor | approved | M7 |
| FRG-TOR-006 | Blocklist by info-hash | tor | approved | M7 |
| FRG-IMP-001 | Single parser implementation for all consumers | imp | implemented | M1 |
| FRG-IMP-002 | Pure, deterministic parse function | imp | implemented | M1 |
| FRG-IMP-003 | Structured parse result with confidence, no sentinels, no crashes | imp | implemented | M1 |
| FRG-IMP-004 | Tokenization and separator handling | imp | implemented | M1 |
| FRG-IMP-005 | Unicode-native handling and single-sourced normalization | imp | implemented | M1 |
| FRG-IMP-006 | Archive extension recognition | imp | implemented | M1 |
| FRG-IMP-007 | Plain integer and #-prefixed issue numbers with leading-title guard | imp | implemented | M1 |
| FRG-IMP-008 | Decimal, negative, and Unicode-fraction issue numbers | imp | implemented | M1 |
| FRG-IMP-009 | Alphanumeric issue suffixes and named issues | imp | implemented | M1 |
| FRG-IMP-010 | Issue ranges | imp | implemented | M1 |
| FRG-IMP-011 | Mini-series counts and cover/page-tag stripping | imp | implemented | M1 |
| FRG-IMP-012 | Volume designators including volume-years | imp | implemented | M1 |
| FRG-IMP-013 | Year and cover-date extraction | imp | implemented | M1 |
| FRG-IMP-014 | Year-equals-issue one-shot disambiguation | imp | implemented | M1 |
| FRG-IMP-015 | Annuals and specials as structured classification | imp | implemented | M1 |
| FRG-IMP-016 | Booktype detection as distinct enum | imp | implemented | M1 |
| FRG-IMP-017 | Generic annotation classification (scan groups, edition tags) | imp | implemented | M1 |
| FRG-IMP-018 | Embedded issue-ID pass-through | imp | implemented | M1 |
| FRG-IMP-019 | Series title output and alternate title splits | imp | implemented | M1 |
| FRG-IMP-020 | Total, collision-free issue ordering keys | imp | implemented | M1 |
| FRG-IMP-021 | Corpus-driven regression suite | imp | implemented | M1 |
| FRG-IMP-022 | Library scan walk | imp | implemented | M2 |
| FRG-IMP-023 | Existing-library import staging and review | imp | implemented | M2 |
| FRG-IMP-024 | Embedded metadata read during import | imp | implemented | M2 |
| FRG-IMP-025 | Story-arc reading-order prefix | imp | approved | B |
| FRG-PP-001 | Single shared import pipeline | pp | implemented | M1 |
| FRG-PP-002 | Completed-download handling state machine | pp | implemented | M1 |
| FRG-PP-003 | Grab reconciliation by download ID | pp | implemented | M1 |
| FRG-PP-004 | Import evidence aggregation | pp | implemented | M1 |
| FRG-PP-005 | Import decision specifications with visible reasons | pp | implemented | M1 |
| FRG-PP-006 | Archive validity verification | pp | implemented | M1 |
| FRG-PP-007 | Safe file operations | pp | implemented | M1 |
| FRG-PP-008 | Remote path mapping | pp | implemented | M1 |
| FRG-PP-009 | Token-based renaming engine | pp | implemented | M1 |
| FRG-PP-010 | Folder templates and folder lifecycle | pp | implemented | M1 |
| FRG-PP-011 | Import history events | pp | implemented | M1 |
| FRG-PP-012 | Rename preview before execution | pp | implemented | M2 |
| FRG-PP-013 | Upgrades and deletions via recycle bin | pp | implemented | M2 |
| FRG-PP-014 | Duplicate constraint handling | pp | implemented | M2 |
| FRG-PP-015 | Failed-download blocklist and auto re-search | pp | withdrawn | — |
| FRG-PP-016 | Manual import resolution | pp | implemented | M2 |
| FRG-PP-017 | ComicInfo.xml tagging on import | pp | implemented | M2 |
| FRG-PP-018 | CBR-to-CBZ conversion and library-wide retagging | pp | approved | B |
| FRG-PP-019 | Permissions and ownership enforcement | pp | approved | B |
| FRG-API-001 | Versioned, OpenAPI-documented REST API | api | implemented | M1 |
| FRG-API-002 | Standard error and resource conventions | api | implemented | M1 |
| FRG-API-003 | Series resources with ComicVine lookup | api | implemented | M1 |
| FRG-API-004 | Issue resources with monitored toggle | api | implemented | M1 |
| FRG-API-005 | Command endpoint for background actions | api | implemented | M1 |
| FRG-API-006 | Paging envelope for list endpoints | api | implemented | M1 |
| FRG-API-007 | Queue endpoint backed by tracked downloads | api | implemented | M1 |
| FRG-API-008 | Release endpoint: interactive search with cached grab | api | implemented | M1 |
| FRG-API-009 | Provider schema and test endpoints | api | implemented | M1 |
| FRG-API-010 | WebSocket resource-change push | api | implemented | M1 |
| FRG-API-011 | History endpoint | api | implemented | M2 |
| FRG-API-012 | Wanted/missing endpoint | api | implemented | M2 |
| FRG-API-013 | Config resource endpoints | api | implemented | M2 |
| FRG-API-014 | System status, health, and task endpoints | api | implemented | M2 |
| FRG-API-015 | Manual import endpoint | api | implemented | M2 |
| FRG-API-016 | Parse debug endpoint | api | approved | B |
| FRG-API-017 | ComicVine suggest (bounded lookup variant) | api | implemented | M2 |
| FRG-API-018 | ComicVine credential settings resource | api | implemented | M2 |
| FRG-API-019 | Pull/weekly resource endpoint | api | implemented | M3 |
| FRG-API-020 | Series grouping projection | api | implemented | M3 |
| FRG-API-021 | Log records resource | api | implemented | M4 |
| FRG-API-022 | Containment resources | api | implemented | M4 |
| FRG-API-023 | Creators resource and follow toggle | api | implemented | M5 |
| FRG-API-024 | Creator bibliography resource | api | implemented | M5 |
| FRG-UI-001 | SPA architecture: server state via React Query + WS invalidation | ui | implemented | M1 |
| FRG-UI-002 | Design token layer with ant/foraging theme | ui | implemented | M1 |
| FRG-UI-003 | Library index screen | ui | implemented | M1 |
| FRG-UI-004 | Series detail screen | ui | implemented | M1 |
| FRG-UI-005 | Add-series search screen | ui | implemented | M1 |
| FRG-UI-006 | Activity: queue screen | ui | implemented | M1 |
| FRG-UI-007 | Interactive search overlay | ui | implemented | M1 |
| FRG-UI-008 | Settings: indexers with schema-driven forms and test buttons | ui | implemented | M1 |
| FRG-UI-009 | Settings: download clients | ui | implemented | M1 |
| FRG-UI-010 | Activity: history screen | ui | implemented | M2 |
| FRG-UI-011 | Wanted screen | ui | implemented | M2 |
| FRG-UI-012 | Settings: media management and naming with rename preview | ui | implemented | M2 |
| FRG-UI-013 | Settings: notifications | ui | approved | B |
| FRG-UI-014 | Manual import overlay | ui | implemented | M2 |
| FRG-UI-015 | Library import (existing files) flow | ui | implemented | M2 |
| FRG-UI-016 | System status and tasks screens | ui | implemented | M2 |
| FRG-UI-017 | Blocklist screen | ui | implemented | M2 |
| FRG-UI-018 | Weekly pull / calendar view | ui | implemented | M4 |
| FRG-UI-019 | Global header quick-search over the local library | ui | implemented | M2 |
| FRG-UI-020 | Settings: General with ComicVine metadata credential | ui | implemented | M2 |
| FRG-UI-021 | Grouped library view | ui | implemented | M3 |
| FRG-UI-022 | Collected-edition (trade) surfacing | ui | implemented | M3 |
| FRG-UI-023 | Application shell | ui | implemented | M4 |
| FRG-UI-024 | System → Logs screen | ui | implemented | M4 |
| FRG-UI-025 | Issue bulk selection and actions | ui | implemented | M4 |
| FRG-UI-026 | Collections tab | ui | implemented | M4 |
| FRG-UI-027 | Creators grid screen | ui | implemented | M5 |
| FRG-UI-028 | Creator profile screen | ui | implemented | M5 |
| FRG-UI-029 | Sources screen | ui | approved | M6 |
| FRG-SRC-001 | store-source model and connection lifecycle | sources | approved | M6 |
| FRG-SRC-002 | Humble session-cookie authentication | sources | approved | M6 |
| FRG-SRC-003 | entitlement sync | sources | approved | M6 |
| FRG-SRC-004 | review-first entitlement workflow | sources | approved | M6 |
| FRG-SRC-005 | session expiry as a modeled state | sources | approved | M6 |
| FRG-SRC-006 | entitlement download and import handoff | sources | approved | M6 |
| FRG-SRC-007 | collected-edition reconciliation never suppresses singles | sources | approved | M6 |
| FRG-OPDS-001 | OPDS 1.2 Atom catalog with navigation root | opds | implemented | M1 |
| FRG-OPDS-002 | Acquisition feeds with per-entry metadata | opds | implemented | M1 |
| FRG-OPDS-003 | Library-id-based file resolution only (no client-supplied paths) | opds | implemented | M1 |
| FRG-OPDS-004 | Parameterized queries throughout | opds | implemented | M1 |
| FRG-OPDS-005 | Whole-file download with correct comic MIME types | opds | implemented | M1 |
| FRG-OPDS-006 | Feed pagination with totals | opds | implemented | M1 |
| FRG-OPDS-007 | Working OpenSearch (or none) | opds | implemented | M2 |
| FRG-OPDS-008 | OPDS-PSE page streaming | opds | implemented | M3 |
| FRG-OPDS-009 | Cached page counts and page index | opds | implemented | M3 |
| FRG-OPDS-010 | Natural page ordering within archives | opds | implemented | M3 |
| FRG-OPDS-011 | Cover and thumbnail links with local fallback | opds | implemented | M3 |
| FRG-OPDS-012 | Resource limits on archive and image handling | opds | implemented | M3 |
| FRG-OPDS-013 | Recent Additions shelf | opds | implemented | M2 |
| FRG-OPDS-014 | Publisher browse shelf | opds | approved | B |
| FRG-OPDS-015 | Single OPDS version; no OPDS 2.0 | opds | approved | B |
| FRG-NOTIF-001 | Generic notifier provider abstraction | notif | approved | B |
| FRG-NOTIF-002 | Event catalog with per-connection opt-in | notif | approved | B |
| FRG-NOTIF-003 | Event payload content | notif | approved | B |
| FRG-NOTIF-004 | Test action per connection | notif | approved | B |
| FRG-NOTIF-005 | Starter channel set | notif | approved | B |
| FRG-NOTIF-006 | Additional channels (deferred) | notif | approved | B |
| FRG-NOTIF-007 | Delivery isolation and failure handling | notif | approved | B |
| FRG-NOTIF-008 | Cover image attachments | notif | approved | B |
| FRG-DB-001 | single SQLite database under /config | db | implemented | M1 |
| FRG-DB-002 | versioned schema migrations | db | implemented | M1 |
| FRG-DB-003 | pre-migration automatic backup | db | implemented | M1 |
| FRG-DB-004 | refuse to run against a newer schema | db | implemented | M1 |
| FRG-DB-005 | WAL journal mode with busy timeout | db | implemented | M1 |
| FRG-DB-006 | single-writer discipline | db | implemented | M1 |
| FRG-DB-007 | transactional multi-step operations | db | implemented | M1 |
| FRG-DB-008 | typed, sentinel-free schema | db | implemented | M1 |
| FRG-DB-009 | scheduled backups with retention | db | implemented | M2 |
| FRG-DB-010 | restore from backup | db | implemented | M2 |
| FRG-DB-011 | library export and import | db | approved | B |
| FRG-DB-012 | integrity verification | db | implemented | M2 |
| FRG-SCHED-001 | command abstraction for background work | sched | implemented | M1 |
| FRG-SCHED-002 | persisted command queue surviving restart | sched | implemented | M1 |
| FRG-SCHED-003 | command de-duplication | sched | implemented | M1 |
| FRG-SCHED-004 | priority and exclusivity | sched | implemented | M1 |
| FRG-SCHED-005 | worker pools per workload class | sched | implemented | M1 |
| FRG-SCHED-006 | interval scheduler | sched | implemented | M1 |
| FRG-SCHED-007 | force-run of any scheduled task | sched | implemented | M1 |
| FRG-SCHED-008 | persisted job history | sched | implemented | M1 |
| FRG-SCHED-009 | in-process event bus | sched | implemented | M1 |
| FRG-SCHED-010 | command status push to UI | sched | implemented | M2 |
| FRG-SCHED-011 | graceful queue drain on shutdown | sched | implemented | M1 |
| FRG-DEP-001 | Docker image per linuxserver.io conventions | dep | implemented | M1 |
| FRG-DEP-002 | all persistent state under /config | dep | implemented | M1 |
| FRG-DEP-003 | configuration via environment variables and config file | dep | implemented | M1 |
| FRG-DEP-004 | versioned config-file migration | dep | implemented | M2 |
| FRG-DEP-005 | secrets never in image or repository | dep | implemented | M1 |
| FRG-DEP-006 | structured logging | dep | implemented | M1 |
| FRG-DEP-007 | health endpoint | dep | implemented | M1 |
| FRG-DEP-008 | graceful shutdown | dep | implemented | M1 |
| FRG-DEP-009 | no self-update (explicit divergence from Mylar) | dep | implemented | M1 |
| FRG-DEP-010 | version and build info | dep | implemented | M1 |
| FRG-DEP-011 | Tailscale-scoped exposure | dep | implemented | M1 |
| FRG-DEP-012 | secrets-stripped diagnostic bundle | dep | approved | B |
| FRG-DEP-013 | First-run default DDL provider seeding | dep | implemented | M2 |
| FRG-DEP-014 | Open-source license (GPL-3.0) | dep | implemented | — |
| FRG-AUTH-001 | M1/M2 no-auth accepted risk | auth | implemented | M1 |
| FRG-AUTH-002 | single-user web login | auth | approved | M8 |
| FRG-AUTH-003 | password storage with modern KDF | auth | approved | M8 |
| FRG-AUTH-004 | session management | auth | approved | M8 |
| FRG-AUTH-005 | HTTP Basic for OPDS realm | auth | approved | M8 |
| FRG-AUTH-006 | API keys separate from session auth | auth | approved | M8 |
| FRG-AUTH-007 | API key lifecycle | auth | approved | M8 |
| FRG-AUTH-008 | at-rest secret encryption | auth | approved | M6 |
| FRG-AUTH-009 | login rate limiting and audit | auth | approved | M8 |
| FRG-AUTH-010 | uniform coverage of all surfaces | auth | approved | M8 |
| FRG-NFR-001 | startup time | nfr | implemented | M2 |
| FRG-NFR-002 | library scan throughput | nfr | implemented | M2 |
| FRG-NFR-003 | UI responsiveness at library scale | nfr | implemented | M2 |
| FRG-NFR-004 | ComicVine rate limiting | nfr | implemented | M1 |
| FRG-NFR-005 | indexer and DDL politeness with failure backoff | nfr | implemented | M1 |
| FRG-NFR-006 | bounded, verified outbound requests | nfr | implemented | M1 |
| FRG-NFR-007 | crash-safe queues and idempotent work | nfr | implemented | M2 |
| FRG-NFR-008 | secret redaction in logs and errors | nfr | implemented | M1 |
| FRG-NFR-009 | configuration validation at startup | nfr | implemented | M1 |
| FRG-NFR-010 | resilience to external-service failure | nfr | implemented | M1 |
| FRG-NFR-011 | observable component health | nfr | implemented | M2 |
| FRG-NFR-012 | untrusted external content handling | nfr | implemented | M1 |
| FRG-NFR-013 | resource footprint | nfr | approved | B |
| FRG-SEC-001 | SSRF egress controls for server-side fetches | sec | implemented | M1 |
| FRG-SEC-002 | Hardened XML parsing (XXE / entity-expansion) | sec | implemented | M1 |
| FRG-SEC-003 | Archive-processing safety (bomb / zip-slip limits) | sec | implemented | M1 |
| FRG-SEC-004 | Filesystem path confinement (safe-join) | sec | implemented | M1 |
| FRG-SEC-005 | CSRF stance and WebSocket Origin validation | sec | approved | M8 |
| FRG-NFR-014 | Listener request resource limits | nfr | implemented | M2 |
| FRG-NFR-015 | Bounded log capture with configurable retention | nfr | implemented | M4 |
| FRG-QUAL-001 | Format profile entity | qual | implemented | M1 |
| FRG-QUAL-002 | Default profile seeded on first run | qual | implemented | M1 |
| FRG-QUAL-003 | Release preferred-term scoring | qual | approved | B |
| FRG-QUAL-004 | Per-profile size bounds | qual | approved | B |
| FRG-QUAL-005 | Profile management UI and API | qual | approved | B |
