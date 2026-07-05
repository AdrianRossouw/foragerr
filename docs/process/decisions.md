# Decision Index

A chronological index of architecture/process decisions. The **authoritative record**
of each decision is the `## Decisions` section of the change design doc (or the plan/
proposal) that made it — this file only points there; do not restate rationale here.
Update this index as part of each change's merge step.

Location key: `changes/<id>` = `openspec/changes/<id>/design.md` (moves to
`openspec/changes/archive/YYYY-MM-DD-<id>/design.md` on archive).

| Date | Decision | Where recorded |
|------|----------|----------------|
| 2026-07-04 | M1 implemented as 7 medium changes (+ change 8: Playwright E2E), dependency spine 1‖2 → 3..7 | Phase 3 plan (owner-approved); summarized in each proposal's Why |
| 2026-07-04 | Backend stack: Python 3.12 + uv, FastAPI, Pydantic v2, SQLAlchemy 2 + Alembic, aiosqlite, httpx, defusedxml | changes/m1-foundation §Tech (design Context + proposal Impact) |
| 2026-07-04 | Frontend stack: Vite + React + TS, TanStack Query, single WS-listener invalidation | Phase 3 plan; UI spec (FRG-UI-001) |
| 2026-07-04 | Single-writer discipline via one async write lock (not a writer task/queue) | changes/m1-foundation design §Decisions 2 |
| 2026-07-04 | Alembic forward-only at startup; refuse-newer-schema instead of downgrade scripts; pre-migration backup w/ retention | changes/m1-foundation design §Decisions 3 |
| 2026-07-04 | Hand-rolled ≤60s scheduler loop over a scheduled_tasks table — explicitly not APScheduler | changes/m1-foundation design §Decisions 5; sched spec FRG-SCHED-006 Notes |
| 2026-07-04 | One shared outbound HTTP factory; TLS always on; manual redirect walk (max 5) with per-hop SSRF egress validation; external vs local-service profiles; DNS-rebinding TOCTOU accepted residual (RISK-025) | changes/m1-foundation design §Decisions 9 |
| 2026-07-04 | Config = /config/config.yaml (first-run generated) with FORAGERR_* env precedence; pydantic-settings fail-fast | changes/m1-foundation design §Decisions 7 |
| 2026-07-04 | Structured logging via stdlib + redaction Filter; secrets self-register at config load | changes/m1-foundation design §Decisions 8 |
| 2026-07-04 | No auth in M1 (RISK-020 accepted; Tailscale-only compensating control); no dormant auth code | changes/m1-foundation design §Decisions 11; auth spec FRG-AUTH-001 |
| 2026-07-04 | Parser: pure stdlib package, staged pipeline (not regex monolith); typed frozen results, no sentinels, zero-crash bar | changes/m1-filename-parser design §Decisions 1-3 |
| 2026-07-04 | Issue ordering key = (Fraction value, class rank, suffix rank) tuple — collision-free total order | changes/m1-filename-parser design §Decisions 4 |
| 2026-07-04 | Parser corpus as additive-only data table with per-row FRG tags; corrected (not Mylar) expectations pinned | changes/m1-filename-parser design §Decisions 5 |
| 2026-07-04 | Wanted is a derived query — no stored wanted column anywhere | changes/m1-library-metadata design §Decisions 2 |
| 2026-07-04 | Add flow = chained persisted commands (add → refresh → scan → optional search), add_options cleared after first application | changes/m1-library-metadata design §Decisions 3 |
| 2026-07-04 | Refresh reconciliation: delete arm skipped on partial fetch; issues with files never hard-deleted | changes/m1-library-metadata design §Decisions 4 |
| 2026-07-04 | Process-global ComicVine rate limiter (one gate for all call sites incl. covers) | changes/m1-library-metadata design §Decisions 6 |
| 2026-07-04 | M1 series-path template fixed; full token engine deferred to the PP renaming engine (change 6) | changes/m1-library-metadata design §Decisions 11 |
| 2026-07-04 | Per-change merge gate: suite green → /code-review (medium, diff-scoped) → /simplify → suite + trace.py → merge | Owner directive (session 2026-07-04); this file is the record |
| 2026-07-04 | Model split while Fable preview lasts: Fable = specs/orchestration/foundational reviews; Opus = subtle implementation; Sonnet = mechanical implementation + simplify | Owner directive (session 2026-07-04); this file is the record |
| 2026-07-05 | Command-chaining needs the enqueuing `CommandService` inside a handler; `HandlerContext` gained an optional `commands` field wired by `CommandService.__init__` (backwards compatible) rather than threading it through every call site | `library/flows/_common.py`; `commands/service.py::HandlerContext` (m1-library-metadata, now archived) |
| 2026-07-05 | Cover-cache "re-fetch only on CV image-URL change" tracked via a `<id>.url` sidecar file next to the cached JPEG, not a DB column — `library.models` was a frozen input to this change; the DB commit of `cover_cached_at` happens before the sidecar write so a crash between the two self-heals on the next refresh instead of leaving it permanently stale | `library/flows/_common.py::cover_paths`, `library/flows/refresh.py::_cache_cover_best_effort` |
| 2026-07-05 | Scan-time series-title matching is one-directional (parsed filename's tokens must be a subset of the series' own key, never the reverse) — the symmetric form let a short series name (e.g. "Batman") swallow a misfiled file belonging to a different, longer-named series ("Batman Beyond"); found in the m1-library-metadata review gate | `library/flows/scan.py::_series_title_matches` |
| 2026-07-05 | Milestone reshape: M2 = "own your library" (~35: import cluster, naming/file-safety, visibility screens, Recent+search OPDS shelves, backups, NFR hardening, quality trio); M3 = comics-native (PULL area + UI-018 promoted from B; OPDS-PSE cluster; volume-grouping/trade ids at proposal time); M4 = sources (Humble Bundle, ids at proposal time); M5 = auth (AUTH-002..010 + SEC-005). Torrents (TOR-*, IDX-012) and notifications (NOTIF-*, UI-013) parked to B. Trades never suppress single-issue wanted state. M2 backups will record plaintext-provider-credentials-in-backups as an accepted risk (AUTH-008 stays M5) | Owner decisions (session 2026-07-05); registry legend; comics-domain memo |
