# m4-library-views — tasks

## 1. Setup

- [x] 1.1 Branch `change/m4-library-views` (no new IDs — MODIFIED UI-003/021)

## 2. Views

- [x] 2.0 Brand mark from the updated handoff: `LogoMarkIcon` + lockup CSS to
      the exact spec via `--color-logo-*` tokens, Roboto 900 weight, SVG
      favicon (FRG-UI-023/002; no spec delta)
- [x] 2.1 Shared primitives as needed (ProgressStrip, Chip, Menu/Dropdown,
      SegmentedControl) under components/, tokens-only styling (FRG-UI-002)
- [x] 2.2 Posters view: auto-fill grid, S/M/L sizes, card anatomy (bookmark,
      publisher/volume chips, progress strip, title/subline), publisher tint
      fallback before art (FRG-UI-003)
- [x] 2.3 Overview view: rows with thumb, status pill, wide progress, %
      (FRG-UI-003)
- [x] 2.4 Table view: dense columns per the design (FRG-UI-003)
- [x] 2.5 Grouped mode: stacked poster cards (layered shadow, N-vols chip,
      summed progress); keep header/nested behavior in row contexts and the
      FRG-SER-017 affordance (FRG-UI-021)

## 3. Toolbar

- [x] 3.1 View switcher + Options/Sort/Filter raised menus (size segmented,
      group toggle; sort check; filter counts); content-click closes menus;
      persistence of view/size/sort/filter (FRG-UI-003)
- [x] 3.2 Count line with semantic colors (FRG-UI-003)

## 4. Tests & docs

- [x] 4.1 Vitest per scenario set (FRG-UI-003/021 in test names); keep
      `library-poster-grid` and SELECTORS.md stable; e2e spine green
      (271 vitest green; spine 14/14 GREEN 2026-07-10)
- [x] 4.2 `docs/manual/user/library.md` view modes + menus (FRG-PROC-011)
- [ ] 4.3 Regenerate the tour (FRG-PROC-017)

## 5. Merge gate

- [ ] 5.1 Full checklist; CHANGELOG v0.4.2 + bump (FRG-PROC-007/013/015)
- [ ] 5.2 Review cycle (angles + Codex ninth); sync delta; archive; merge;
      tag; push; release
