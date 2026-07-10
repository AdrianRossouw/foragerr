# m4-series-detail — design

## Context

M4 ch4 (standing grant). Sources: design handoff §2 (series detail —
re-extract the zip in docs/research/ to the session scratchpad; dc.html
lines ~178–300 carry the exact hero/panel/table markup), the owner's
2026-07-10 demo UX feedback (bulk actions, shift-range select, show-more),
and the 2026-07-10 containment research report (Mylar cv.py TPB scraping,
our sanitizer's link stripping, schema precedents).

## Decisions

1. **Containment = declared ranges in a side table, keyed by ordering-key
   bounds.** `issue_collections(id, trade_issue_id FK CASCADE,
   target_series_id FK CASCADE, start_ordering_key, end_ordering_key,
   range_label, source CHECK('declared','derived_description'),
   confidence, created_at)` — one row per contiguous sub-range; endpoints
   are copied ordering keys (robust to CV renumbering, `BETWEEN`-comparable,
   the comparator the schema already uses). No column on `series`/`issues`.
   Migration 0015 is a pure new table (`create_table` with inline FK
   constraints — the 0013 raw-ALTER pattern is only needed when adding FK
   columns to an existing table).
2. **Display-only is proven by absence, same as FRG-SER-019.** The M3
   invariant test asserting no booktype predicate in
   `wanted_issues`/`series_statistics` is extended: their compiled SQL must
   reference neither `issue_collections` nor its columns. Coverage status
   (Collected / Partial / Not collected) is a request-time read rollup over
   `exists(IssueFileRow)` within the range — modeled on the grouping
   rollup layer — never persisted.
3. **Declared-only in v1.** The operator declares ranges from a dialog
   (target series limited to the library, start/end chosen from that
   series' issue list — annuals excludable by choosing endpoints). CV
   description parsing ships later as non-binding suggestions; the
   `source`/`confidence` columns exist so that lands without a migration.
4. **Bulk actions ride the existing bulk-monitor mutation** and the
   existing per-issue search command, batched client-side for "Search
   selected" (sequential dispatch with the shared command-status surface).
   Shift-range selection is anchor-based (last non-shift click is the
   anchor; shift-click selects the visible-row span between).
5. **Show-more overview**: collapsed to a fixed line clamp when the text
   overflows (measured, not char-counted); expanded state is
   component-local (not persisted).
6. **Hero backdrop** uses the local cover endpoint (never an external
   host), blur+darken via CSS on a positioned underlay — tokens-only
   styling; the 2:3 sharp cover reuses the shared Poster.

## Risks / Trade-offs

- [New unauthenticated write surface (containment endpoints)] → same
  RISK-020 tailnet-only acceptance as every existing write endpoint;
  recorded in threat model/risk register. Input validation: target series
  must exist, ordering bounds must belong to it and be ordered.
- [Wanted-invariant regression] → decision 2's absence test; LARGE-tier
  gate includes a dedicated invariant angle.
- [e2e selector breakage on the rebuilt table] → `issue-row-<issueId>`,
  per-row accessible names, `interactive-search-overlay`, `command-status`
  kept stable (SELECTORS.md contract).
- [Bulk search flooding] → "Search selected" dispatches sequentially via
  the existing command queue (no parallel fan-out) and is capped per batch.

## Migration Plan

Additive migration 0015; rollback = revert (forward-only per FRG-DB
policy, table is ignorable if unused). Frontend/back deployed together as
ever (single image).

## Open Questions

- None.
