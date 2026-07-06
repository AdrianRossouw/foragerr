# Design — m2-daily-surfaces

## Context

All the data these surfaces read already exists; the change is mostly read
APIs + screens + two event writers + one WS event + two OPDS feeds. Grounding
(research-verified): `ImportHistoryRow` + `record_event` (canonical sorted-JSON
`data`) with reads but no HTTP surface; `grabbed`/`download_failed` are in the
event vocabulary with ZERO writers (grabs live in `grab_history`, failures in
`blocklist`); RISK-040's duplicate rows are written at `pipeline.py`'s
not-approved branch each retry cycle; `repo.wanted_issues()` is the canonical
derived-missing SELECT (backlog search already walks it); blocklist has
writers but no read/delete API; `CommandStatusChanged` fires on queued +
terminal but NOT on the started claim; OPDS root advertises no search (the
compliant "none"); `delete_issue_file` is implemented/tested with zero
callers; SeriesDetail's delete-files checkbox always 501s.

## Goals / Non-Goals

**Goals:** history/wanted/blocklist read surfaces + screens; single-source
history feed; RISK-040 row dedup; started-transition push; OPDS Recent +
OpenSearch(a); delete-files wiring end to end.

**Non-Goals:** cutoff-unmet; notifications; scheduled refresh; history
retention/pruning (ch5 if wanted); blocklist WRITE behavior changes.

## Decisions

1. **History is single-source going forward**: write `EVENT_GRABBED` (in
   `search_ops/grab.py`, beside the `grab_history` insert — that table keeps
   its operational match-key role) and `EVENT_DOWNLOAD_FAILED` (in
   `downloads/tracking.py::process_failures`, beside the blocklist write).
   The endpoint reads `import_history` only. Pre-change grabs won't backfill —
   acceptable pre-release; no 3-way UNION forever. Alternative (union query)
   rejected: permanent complexity for one-time historical completeness.
2. **RISK-040 dedup at the writer seam**: `record_event_deduped` in
   `importer/history.py` — skip when the newest `import_blocked`/
   `import_failed` row for the same `download_id` has identical `event_type` +
   canonical `data` string (sorted-keys JSON makes string equality correct).
   Used by BOTH pipeline not-approved sites (rejection + exception paths).
   The tracking retry loop is untouched (deliberate, load-bearing). Risk
   register: RISK-040 → Mitigate, disposition updated.
3. **Endpoints copy the queue pattern**: `paginate()` over the single entity,
   batch-load series/issues, Pydantic resources with nested display objects,
   whitelisted sorts. `GET /history` (filters: eventType, seriesId),
   `GET /wanted/missing` (over `repo.wanted_issues()` — importing it from
   `library.repo` is cycle-safe), `GET /blocklist` + `DELETE /blocklist/{id}`
   (+ bulk via ids body). New small routers; no new tables.
4. **SCHED-010**: emit `CommandStatusChanged(status="started")` inside
   `_claim_next`'s write session (same `queue_event` mechanics as the other
   two sites). Tagged test drives a WS client through queued→started→terminal
   (coalescing may merge frames but the terminal state always lands —
   assert started is observable with the debounce window respected).
5. **Frontend pagination becomes real**: a small `usePagedQuery` helper
   (family key `['history', page]` etc. per the queue's key convention),
   page controls component shared by History/Blocklist (Wanted too).
   History/Wanted/Blocklist go in the sidebar: History + Blocklist under
   Activity, Wanted top-level (Sonarr shape). WS: add `history`, `wanted`,
   `blocklist` invalidation branches only where a backend event actually
   fires (imports/deletes → history+wanted; blocklist writes → blocklist).
6. **OPDS Recent**: `/recent` route via the shared `_count_and_page` +
   `_issue_file_entry` helpers, `ORDER BY issue_files.added_at DESC`; root
   feed entry beside All Series. No new config: FRG-OPDS-006 page sizing
   bounds it.
7. **OpenSearch option (a)**: root `rel="search"` link → static descriptor
   (`application/opensearchdescription+xml`, template
   `/opds/search?q={searchTerms}`) → search feed matching series by
   case-folded title/alias containment (ORM bound parameters; reuse
   `matching_key` folding for resilience), returning navigation entries into
   existing series acquisition feeds. Input bounded (length cap), output via
   the escaping atom builder, adversarial cases added to
   `test_opds_security.py`. Threat-model delta: new untrusted query input on
   the unauthenticated listener.
8. **Delete-files wiring**: new `api/issuefile.py` router —
   `DELETE /api/v1/issuefile/{id}` → existing `delete_issue_file`
   (404 on `IssueFileNotFoundError`); the flow's history event switches to
   `source=manual` for this path (it is a user action, not a rescan).
   `delete_series(delete_files=True)` implements: iterate the series' files
   through the same recycle-routing BEFORE row deletion (compensation
   pattern already in `delete_issue_file`); the API's 501 mapping goes away.
   SeriesDetail: per-issue-row delete-file action (confirmation names the
   bin-or-permanent consequence) + the dialog checkbox now truthful.
   WS/query invalidation: series detail + wanted + history.

## Risks / Trade-offs

- [Dedup hides a legitimately repeated identical outcome] → only suppressed
  for the SAME downloadId with byte-identical payload; any evidence change
  writes. History still shows the first occurrence; the queue shows the live
  blocked state. Acceptable by design.
- [OpenSearch on an unauthenticated listener] → bound params + escaping
  builder + length cap + security tests; no new data exposure (series titles
  are already listed in the catalog).
- [Series delete-files on a huge series is slow in-request] → run via the
  existing command/offload seams if measurable; otherwise accept (single
  user, bounded by series size). Decide during implementation with a test
  at realistic size.
- [History page-1 invalidation storms under bursty imports] → WS coalescing
  already debounces; invalidation is per-family, refetch is one page.

## Migration Plan

No migrations. Rollback = revert merge.

## Open Questions

None.
