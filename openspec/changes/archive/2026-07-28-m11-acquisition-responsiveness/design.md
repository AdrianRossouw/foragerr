# m11-acquisition-responsiveness — design

## Context

Research (2026-07-28) established: the interactive fan-out is a bare
`asyncio.gather` with no timeout anywhere (`search_ops/pipeline.py`
`_fan_search`); slowness accumulates in `indexers/service.py`'s
sequential paging (up to 20 pages × 2s politeness, 30s per-request read
timeout, no per-indexer overall budget) and the listener's
time-to-first-byte guard (default 30s) then kills the whole request.
`IndexerSearchOutcome` already carries per-indexer failure state — the
timed-out outcome extends it. The per-series bounded search already
exists and is wired to add behind the `search_on_add` checkbox
(`refresh.py:278-285`); FRG-SER-005's scenario text even names this
change. Next-run data for backlog-search already exists on the Tasks
surface. The Die-Loaded stall is a designed retry ping-pong
(`import_blocked` → tracking resets to `import_pending` while the
client reports COMPLETED) with no consecutive-stall memory anywhere.
Indexer priority shipped in the UI 2026-07-05; the download-client form
lacks it while FRG-UI-009's scenario claims it renders.

## Goals / Non-Goals

**Goals:** interactive search returns useful results in bounded time
with honest per-indexer outcomes; a fresh install acquires its first
wanted issues without waiting six hours; a stalled completed download
becomes a health problem, not a queue curiosity; the client form stops
contradicting its spec.

**Non-Goals:** async job+poll search redesign; remote path mappings;
backlog cadence changes; grab/decision/comparator changes.

## Decisions

**D1 — Budget the fan-out with `asyncio.wait`, not per-request
surgery.** `_fan_search` wraps each indexer task with a per-indexer
deadline (`indexer_search_time_budget_seconds`, default 20, clamped
5–60: default × politeness stays under the 30s listener guard with
headroom for decisioning). At the deadline, done tasks contribute
results; pending tasks are cancelled cleanly (the politeness gate and
httpx handle cancellation; the indexer client already isolates
failures) and reported as a `timed_out` `IndexerSearchOutcome` carrying
the budget. The backlog path keeps unbudgeted behavior (it has no
listener and politeness matters more than latency) — the budget applies
to the interactive path only, matching the finding.

**D2 — Outcomes ride the response.** The release response gains an
additive `indexers` array (per-indexer: id, name, outcome
searched/timed-out/failed/backing-off, and counts) built from the
outcomes the pipeline already collects. FRG-UI-041 renders it as a
compact strip above the results; a partial result is visibly partial.

**D3 — Default mini-sweep = the existing chain, unconditionally, for
monitored adds.** `refresh.py`'s conditional enqueue becomes: always
enqueue `series-search` for a newly added series whose monitoring
strategy yields wanted issues; the `search_on_add` option's semantics
are unchanged (it remains the explicit request recorded on
add-options; the default sweep is the same bounded command). Dedup
semantics already collapse the double-enqueue when both fire.
First-indexer-configured trigger: the indexer-create endpoint, when the
created indexer is the FIRST enabled one, enqueues one `backlog-search`
run (bounded by its existing walk; politeness gaps stand) — the
fresh-install order (series first, indexer second) gets its sweep from
the indexer side.

**D4 — Next-search surfacing is a read, not new plumbing.** The Wanted
screen shows "next automatic search at …" from the existing scheduled-
task resource (`backlog-search` row's next_run); no new endpoint.

**D5 — Stall memory is two columns, incremented at one seam.**
Migration 0028 adds `import_stall_count` (int, default 0) and
`first_stalled_at` (nullable) to tracked_downloads. The drain's
no-importable-files terminal branch increments the count and stamps
first_stalled_at once; ANY successful import or a genuinely new
evidence outcome resets both. Tracking's ping-pong reset to
import_pending does NOT clear the memory — the memory exists precisely
to survive the ping-pong. A new `downloads` health component reports
rows past `import_stall_threshold_cycles` (default 5) as degraded with
mount/path-mapping guidance, aggregated (one component, counts +
oldest), clearing when no row is past threshold.

**D6 — Client priority is a row-field addition plus a content test.**
`downloadClientKind.rowFields` gains the same numeric priority field
the indexer kind has (advanced, 1–50, default 25 — matching the
backend default and comparator semantics). A content-level test
asserts BOTH provider kinds expose priority so the structural audit
can't pass vacuously; FRG-UI-009's scenario becomes true with no spec
delta (recorded in the proposal).

## Risks / Trade-offs

- [Cancelled indexer tasks mid-page] → cancellation lands between
  politeness waits/HTTP calls; httpx cancellation is clean; the
  outcome records the timeout so nothing silent is lost; grabs only
  ever reference returned rows.
- [Default sweep surprises an operator adding many series] → the sweep
  is per-series-bounded, wanted-only, and politeness-gapped exactly
  like the existing checkbox path; the milestone hard-stop reviews the
  default (called out in the Approval section).
- [Stall threshold false positives on slow mounts] → threshold counts
  consecutive drain cycles (~1/min), default 5 ≈ five minutes; config
  clamps low bound 2; health message names the path so the operator
  recognizes truth immediately.
- [First-indexer trigger firing on a re-created indexer] → the guard is
  first ENABLED indexer (count transitions 0→1); re-creates on a
  populated deployment don't fire.

## Deferred follow-ups (recorded at the simplify pass, 2026-07-28)

1. Straggler rechase: keep parking, reconsider `_rechase_stragglers`
   (speculative; forces tests to reset a module global) — either drop
   or move the set onto an injectable object.
2. Collapse the two overlapping cancelled-unwind guards
   (`_being_cancelled` vs the `task.result()` wrapper) to one — the
   result-wrapper is the more general.
3. `iter_archive_files` grows an any-extension/first-only mode so
   `_holds_any_file` can go.
4. `search_budget_for_path` + exports: inline at the one call site,
   trim the package surface.
5. `_had_enabled_indexer`: guard the create-path read behind
   body.enabled and restate its comment as the upgrade-suppression it
   is (the marker owns concurrency).
6. Health component parallel-structure watch: extract a shared builder
   if a third aggregate component arrives; align `_stamp` usage.
7. Synthetic-fixture enforcement belongs in the four shared support
   modules (conftest, tracking_support, flows_support,
   search_ops/support) — routed to the corpus-synthesis task.

## Migration Plan

Migration 0028: two additive nullable/int-default columns on
tracked_downloads; no data rewrite; inert to older code.

## Open Questions

None blocking.
