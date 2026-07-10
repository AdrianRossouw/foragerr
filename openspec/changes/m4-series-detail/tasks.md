# m4-series-detail — tasks

## 1. Setup

- [x] 1.1 Branch `change/m4-series-detail`; allocate FRG-SER-020 /
      FRG-API-022 / FRG-UI-025 / FRG-UI-026 in the registry

## 2. Backend (containment)

- [x] 2.1 Migration `0015_issue_collections` per the 0013 FK pattern +
      model + migration test (FRG-SER-020)
- [x] 2.2 Repo layer: declare/replace/delete writes with validation;
      collected-in lookup for a series' issues; collections rollup with
      request-time coverage (display-only pattern) (FRG-SER-020/API-022)
- [x] 2.3 Extend the FRG-SER-019 compiled-SQL absence test to
      `issue_collections` (FRG-SER-020)
- [x] 2.4 API endpoints + resources (issues listing chips data, collections
      resource, declare/replace/delete) with standard error shapes
      (FRG-API-022); pytest per scenario, tagged

## 3. Frontend

- [x] 3.1 Detail hero rebuild: blurred local-cover backdrop, sharp cover,
      meta row, action row, show-more overview (FRG-UI-004)
- [x] 3.2 Issues tab table to the design (status pills, collected-in chips,
      size, row actions; selectors contract kept) (FRG-UI-004)
- [x] 3.3 Bulk selection UX: shift-range, select/deselect all, labeled
      action bar wired to bulk monitor + sequential search (FRG-UI-025)
- [x] 3.4 Collections tab + containment dialog (target series picker,
      range pickers, sub-ranges, delete; coverage pills; empty state)
      (FRG-UI-026)
- [x] 3.5 Franchise ⋯ popover a11y unification onto the shared Menu
      behavior (ch2 deferral; FRG-UI-021, no spec change)
- [x] 3.6 Vitest per scenario (IDs in names); e2e spine green

## 4. Docs & security

- [x] 4.1 Threat model / risk register: containment write endpoints
      (no-auth acceptance lineage, tampering note) (FRG-PROC-006)
- [x] 4.2 Manual: series page (detail anatomy, bulk actions, collections/
      containment how-to) + web-ui section (FRG-PROC-011)
- [ ] 4.3 Tour: refresh shots if the detail shot changed (FRG-PROC-017)

## 5. Merge gate (LARGE tier)

- [ ] 5.1 Full suites green; trace 0; soup 0; gitleaks re-scan appended
- [ ] 5.2 Full fleet + Codex (incl. dedicated wanted-invariant angle and a
      security angle on the write endpoints); fixes; CHANGELOG v0.4.4 +
      bump; sync delta; archive; merge; tag; push; release
