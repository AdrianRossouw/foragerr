# m4-design-shell — tasks

## 1. Setup

- [x] 1.1 Branch `change/m4-design-shell`; allocate FRG-UI-023 and
      FRG-PROC-017 in the registry (FRG-PROC-002)

## 2. Tokens

- [x] 2.1 Rebuild the token layer to the handoff palette/type/shape set;
      publisher tint/accent + format-chip maps as data; self-host Roboto +
      FA6 (subset if heavy; SOUP register if package added) (FRG-UI-002)
- [x] 2.2 Tagged tests: token file is the single palette source; built app
      makes no external font/icon requests (FRG-UI-002)

## 3. Shell

- [x] 3.1 AppShell components (Sidebar w/ nav+counts+system+status footer,
      GlobalHeader w/ relocated quick-search + icon buttons, PageToolbar
      slot, scroll-confined Main); shipped-screens-only nav (FRG-UI-023)
- [x] 3.2 Wire nav count badges to existing queries + WS invalidation; warn
      style on Wanted (FRG-UI-023)
- [x] 3.3 Tagged tests: shell frames every route, counts live-update,
      nav lists only implemented routes (FRG-UI-023); e2e selectors stable,
      spine green
- [x] 3.4 Update `docs/manual/user/web-ui.md` shell/navigation sections
      (FRG-PROC-011)

## 4. Screenshot tooling

- [x] 4.1 `tools/refresh-readme-shots.sh` (run→populate→capture→optimize,
      non-zero on missing/over-budget shots) (FRG-PROC-017)
- [x] 4.2 Tagged structural tests (tool exists/executable; README assets ==
      capture shot set) (FRG-PROC-017)
- [x] 4.3 Run the tool against the demo library; commit refreshed README
      assets showing the new shell (FRG-PROC-017, FRG-PROC-014)

## 5. Merge gate

- [x] 5.1 Full checklist (backend+frontend suites, e2e spine, soup, trace,
      config re-scan + evidence, CHANGELOG v0.4.0 + bump, release notes)
      (FRG-PROC-007, FRG-PROC-013, FRG-PROC-015)
- [x] 5.2 Review cycle (angles + Codex ninth); sync deltas; archive; merge
      `--no-ff`; tag; push; release
