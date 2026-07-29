# m11-review-refinements — tasks

## 1. Grab approval gate + force (FRG-API-008)

- [ ] 1.1 Migration 0030: additive `approved` boolean on the
      interactive-search cache table (fail-safe: absent ⇒ not approved)
- [ ] 1.2 `cache_decisions` records each decision's approved verdict;
      `get_cached` returns it beside the hand-off
- [ ] 1.3 `ReleaseGrabRequest` gains `force: bool = false`; `grab_release`
      gates: approved → grab (`interactive`); not-approved + force → grab
      (`interactive-forced`); not-approved + no force → typed 409
- [ ] 1.4 Tagged tests (`FRG-API-008`): approved grabs; rejected refused
      409 without force; rejected forced grab stamped `interactive-forced`;
      pre-0030/NULL approved treated not-approved (fail-safe); cache
      miss/expiry 404 regardless of force

## 2. Group-key sibling sweep + bulk apply-to-group (FRG-SRC-014)

- [ ] 2.1 `group_key`-scoped, `source_id`-scoped sibling-proposal sweep in
      `sources/review.py` (proposal-only, excludes matched/ignored,
      `auto=false`), called from `match_entitlement` AND `_resolve_as_match`
- [ ] 2.2 Bulk apply-to-group action on the bulk endpoint: in-library pick
      bulk-matches members; not-in-library pick adds once + leaves swept
      proposals
- [ ] 2.3 Tagged tests (`FRG-SRC-014`): match-to-existing sweeps siblings;
      add sweeps by group not prior proposal; matched/ignored untouched;
      never crosses `source_id`; bulk apply-to-group both branches; no
      auto-commit

## 3. Frontend affordances (FRG-UI-043, FRG-UI-044)

- [ ] 3.1 `EntitlementGroupHeader` search/match picker seeded with the
      group title, beside select-all/collapse; on pick, bulk-match (have_it)
      or add+sweep+accept (not have_it) over `group.rows`
- [ ] 3.2 `InteractiveSearchOverlay`: "Grab anyway" on rejected /
      temporarily-rejected rows behind a confirm, sends `force: true`;
      approved rows unchanged; reasons stay visible
- [ ] 3.3 Tagged vitest (IDs in names): FRG-UI-043 (group picker matches
      group / adds+proposes); FRG-UI-044 (rejected offers confirmed
      grab-anyway w/ force, approved unchanged)

## 4. Docs + verification

- [ ] 4.1 `docs/manual/user/` search page (Grab anyway) + sources/review
      page (group-header match, sibling sweep); risk register grab/decision
      row notes the force path + audit trail
- [ ] 4.2 Full backend suite (xdist) + frontend (serialized) green; soup 0
- [ ] 4.3 e2e `bash e2e/run.sh` green; traceability regen picks up
      FRG-SRC-014 / FRG-UI-043 / FRG-UI-044
