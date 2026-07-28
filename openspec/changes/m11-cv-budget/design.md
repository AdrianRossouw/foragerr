# m11-cv-budget — design

## Context

Research (2026-07-28) mapped the full surface: one process-global
`_RateGate` with per-path deques over a rolling hour
(`metadata/ratelimit.py`), every API call funnelled through
`ComicVineClient._fetch` plus the covers-cache seam; `budget_health()`
already computes per-bucket used/ceiling/resume at the 80% fraction but
health only reacts at 100%; no structured numbers reach the API surface;
the nightly enrich orders oldest-id-first so a deferred/failing head
restarts at the same position every run; pre-v0.11 stored proposals are
excluded from the pending set forever. An authenticated probe verified
CV's API exposes no usage counters (headers are CDN plumbing; envelope
is pagination only) — calibration-by-reading is off the table.

## Goals / Non-Goals

**Goals:** interactive surfaces never starve behind background spend;
the operator sees the budget before it bites; nightly enrichment
converges across the whole queue; stale proposals get a supported,
budget-aware recompute path.

**Non-Goals:** multi-key (ToS-spirit, spec-recorded), reading CV
counters (verified absent), raising the 150 default, cover-proxy
budgeting (media CDN ≠ API), cross-restart window persistence.

## Decisions

**D1 — Lane is a third dimension on the ONE gate.** `acquire(...,
lane="batch"|"interactive")` (default batch — fail-frugal: an untagged
new caller can never eat the reserve). Batch admission counts against
`floor(budget × batch_share)` (config `comicvine_batch_budget_share`,
default 0.70, clamped 0.30–0.95); interactive admission counts against
the full ceiling. One ledger per bucket, stamps tagged by lane —
refusal math derives both views from one deque, so the FRG-META-016
window/refusal semantics are unchanged in shape. The precedent is
FRG-META-003's amendment note ("both dimensions share the one
process-global gate") — this adds the third the same way.

**D2 — Lane threading at the client constructor.** `ComicVineClient`
gains a `lane` (constructor arg) applied by `_fetch`; `covers.cache_cover`
passes batch explicitly. Callers set it where the client is built:
`enrich.build_cv_client`, refresh/creators/bibliography command paths →
batch; `comicvine_factory` API-route construction, `_operator_cv_client`,
library-import grouping, connection test → interactive. No per-call
threading through business logic.

**D3 — Approaching-limit is a health state, not a new pipe.** The
existing 80% `BUDGET_WARNING_FRACTION` data flows into
`_comicvine_component` as a distinct degraded-class state between ok and
exhausted ("approaching budget ceiling on <bucket>: N/M, batch paused
first"), independent of the 429/auth dimensions per the FRG-META-019
framing. When batch is refused but interactive still has reserve, the
message says exactly that — the warning names the lane that is paused.

**D4 — The meter is structured data on the existing health surface.**
`SystemHealthComponent` gains an optional `detail` object (additive);
for the ComicVine component it carries
`{buckets: [{bucket, used, ceiling, batch_used, batch_ceiling,
resume_seconds}], degraded, exhausted}` — numbers `comicvine_health()`
already computes. No new endpoint. Settings → General renders the full
meter beside the key; the Sources manage bar renders a compact
used/ceiling chip when any bucket is above the warning fraction
(quiet by default — a meter that is always shouting is wallpaper).
The AddSeries lookup outcome note surfaces the backend's typed
budget-resume message instead of the generic failure string.

**D5 — Enrichment orders by attempt, not by id.** Migration 0027 adds
nullable `proposal_attempted_at`; enrich stamps it on every row it
touches in a run (proposed, marker, deferred, errored) and orders the
pending set NULLs-first-then-oldest-attempt, so each run starts where
work is least recent — a failing head can delay its own retry, never the
tail's first attempt. CV-error rows additionally respect a minimum
re-attempt spacing (config, default 24h) instead of every run forever.
FRG-SRC-010's invariant stands: budget hits still leave rows NULL and
retryable; the stamp changes ORDER, never eligibility.

**D6 — Bulk recompute is an operator action riding the batch lane.**
`POST /sources/{id}/recompute-proposals` enqueues a command that walks
rows whose stored proposal predates the CV-first universe (no
`universe` key in the stored JSON — the pre-v0.11 signature) plus, when
the operator opts in via body flag, no-match markers; recomputes in
batches through the batch lane, stamping `proposal_attempted_at`,
stopping cleanly on budget refusal and resuming on the next run of the
same command (the walk is ordered by the D5 stamp, so progress is the
ordering). Operator decisions (matched/ignored) are never touched —
only `new` rows recompute (the FRG-SRC-008/012 stickiness rule).
Marker rows also recompute automatically when the key configuration
transitions no-key → keyed (the `universe:"library-fallback"` markers
are catalog-blind by construction).

**D7 — Docstring correction.** The rate-limit module docstring's "and
cover fetches" claim is scoped to the covers *cache*; the candidate
cover proxy is media-CDN, documented as outside the API budget
(consistent with the v0.9.23 cover-proxy design).

## Risks / Trade-offs

- [Batch share misconfigured low starves background refresh] → clamp
  floor 0.30 + the meter makes the split visible; defaults unchanged
  otherwise.
- [Lane default=batch quietly slows a future interactive caller] →
  fail-frugal is the right default; the meter + approaching warning
  make it observable; interactive call sites are enumerated in tests.
- [Recompute overwrites a proposal the operator was reading] → only
  `new` rows, stored-shape-gated, operator-triggered, and the sweep
  refetch invalidation already covers the UI.
- [Attempt-spacing hides a transient CV error for 24h] → spacing is
  config, the row search and restore bypass it (operator paths), and
  the meter shows why nothing is happening.

## Migration Plan

Migration 0027: nullable `proposal_attempted_at` timestamp on
source_entitlements; no data rewrite; rollback-inert to older code.

## Open Questions

None blocking. The batch-share default (0.70) matches the pre-design's
"~70%" and is config from day one.
