# m11-review-experience — tasks

## 1. Registry and provenance hardening

- [x] 1.1 Allocate FRG-SRC-010, FRG-SRC-011, FRG-SRC-012, FRG-UI-039 in
      docs/traceability/requirements-registry.md (approved/M11); note
      MODIFIED FRG-SRC-003/004, FRG-UI-029 (FRG-PROC-002)
- [x] 1.2 matched_via fail-closed threading: required keyword through the
      review chain, explicit MATCHED_VIA_OPERATOR at every API endpoint,
      auto-accept stays the only auto writer; tests updated (FRG-SRC-004)

## 2. CV-first proposals (FRG-SRC-010)

- [x] 2.1 compute_proposed_match inverted: CV candidates + library
      overlay via cv_volume_id lookup; token-overlap gate before
      similarity; floor on gated candidates; no-key library-only
      fallback recorded on the proposal; deferral semantics preserved
      (FRG-SRC-010)
- [x] 2.2 TPB re-rank from shared cue vocabulary (boost collected-shaped
      candidates for trade-shaped titles; never filter) (FRG-SRC-010)
- [x] 2.3 Tests: zero-overlap-never-proposed (the Absolute Green Arrow
      repro as a fixture), in-library-candidate→match proposal,
      trade-prefers-collected re-rank, no-key fallback, budget-deferral
      non-regression (FRG-SRC-010)

## 3. Bundle identity + bulk accept (FRG-SRC-011)

- [x] 3.1 humble.py parses product.human_name; migration 0026
      bundle_human_name; service persists + backfills on re-sync;
      EntitlementResource exposes it (FRG-SRC-011, FRG-SRC-003)
- [x] 3.2 Bulk action `accept`: server-side per-row own-proposal apply,
      per-row transactions/errors, _bulk idiom; frontend accept loop
      retired (FRG-SRC-011)
- [x] 3.3 Tests: bundle capture + backfill, heterogeneous bulk accept,
      same-title group convergence via FRG-SRC-008 sweep (no 400s),
      per-row error isolation (FRG-SRC-011)

## 4. Publisher rules (FRG-SRC-012)

- [x] 4.1 Per-source publisher rules in settings envelope; classify()
      takes publisher; sync-time reclassification of automatic-hands
      `new` rows only (FRG-SRC-012)
- [x] 4.2 Settings UI: editable list, empty by default, suggested
      starter list as explicit action (FRG-SRC-012)
- [x] 4.3 Tests: rule reclassifies new rows both directions, decided
      rows sticky, empty-by-default, folded matching (FRG-SRC-012)

## 5. Review UI at scale (FRG-UI-039, FRG-UI-029)

- [x] 5.1 Row CV search panel reusing useSuggest/useLookup + outcome
      notes; pick→match / pick→add-and-match; library select retired;
      present on every reviewable row (FRG-UI-039)
- [x] 5.2 Virtualized list (@tanstack/react-virtual — SOUP row) +
      same-title collapse groups w/ mixed-state headers; bundle and
      group selection helpers beside shift-range (FRG-UI-029)
- [x] 5.3 Frontend tests: search-resolves-dead-end row, have_it marking,
      outcome notes, collapse counts + mixed-state header, select-by-
      bundle/group, virtualization smoke at 1,318-row fixture
      (FRG-UI-039, FRG-UI-029)

## 6. Docs, gate, release

- [x] 6.1 Manual: sources.md review workflow (search picker, bundles,
      groups, publisher rules); soup register (react-virtual)
      (FRG-PROC-011, FRG-PROC-012)
- [x] 6.2 Matrix regen; trace/soup/risk green (FRG-PROC-005)
- [x] 6.3 Medium-tier gate + Codex (early pass after first
      implementation commit + delta pass at close) + e2e (FRG-PROC-004)
- [x] 6.4 Live rig verification: the 15-row Batman/Spawn cluster must
      propose sanely (token gate), row search resolves a Spawn row,
      bundle collapse on the real 1,318 corpus
- [x] 6.5 Sync/archive specs, registry flip, release v0.11.0 per
      /release (FRG-PROC-013)
