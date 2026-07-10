# m4-design-shell — design tokens and the new app shell (M4 change 1)

## Why

M4 rebuilds the interface to the owner's design (reviewed 2026-07-10 from the
design handoff, kept outside the repository). Everything downstream — library
views, series detail, add-new, the pull experience — renders inside one shell
and one token set, so those land first. Today's chrome is the M1-era layout;
the design specifies a fixed three-part frame (212px sidebar with nav counts
and a system/status section, 60px global header with search, per-screen
toolbar, content-only scrolling) over a dark warm-neutral palette with a
single green accent and publisher tint/accent palettes.

## What Changes

- **Design token layer rebuilt** (MODIFIED FRG-UI-002): the handoff palette
  (app bg `#202020`, panels `#262626`, accent `#57b877` family, semantic
  status hues, progress track colors, publisher tints/accents, format-chip
  colors), Roboto type scale, radii/spacing/shadow set, Font Awesome 6
  icons — replacing the M1 ant-accent theme. Tokens stay CSS-variable-based
  so downstream M4 changes restyle without re-plumbing.
- **New app shell** (ADDED FRG-UI-023): fixed viewport frame — sidebar (logo
  lockup, nav list with live count badges: Comics = library count, Activity =
  queue length, Wanted = series with missing issues; SYSTEM section with
  Settings/System; footer status row with health pulse + version), global
  header (existing quick-search FRG-UI-019 relocated, health/system icon
  buttons), and a per-screen toolbar slot. **Nav shows shipped screens only**
  — Calendar and Creators entries appear when their screens land (M4 ch5,
  M5), mirroring the README shipped-claims rule.
- **One-command screenshot refresh** (ADDED FRG-PROC-017):
  `tools/refresh-readme-shots.sh` wraps run→populate→capture→optimize against
  the public-domain demo library; every M4 UI change re-runs it before merge
  so the README tour never lags the shipped design (owner instruction
  2026-07-10). This change ends with refreshed screenshots — the first
  visible fruit of the new shell.
- Existing screens render inside the new shell unrestyled (their rebuilds are
  ch2–ch6); e2e selectors preserved or updated with the spine kept green.

## Non-goals

- No screen redesigns (library/series/add-new/pull are ch2–ch5).
- No Calendar or Creators nav entries yet.
- No behavior changes to search, counts, or health data — display relocation
  only.

## Capabilities

### New Capabilities

(none — ui and dev-process capabilities exist)

### Modified Capabilities

- `ui`: FRG-UI-002 modified (token set); FRG-UI-023 added (app shell).
- `dev-process`: FRG-PROC-017 added (regenerable README screenshots).

## Impact

- `frontend/src` theme/tokens + shell components; `e2e` selector updates as
  needed; `tools/refresh-readme-shots.sh` (new) + `e2e/scripts/`
  capture integration; `docs/readme-assets/*` regenerated;
  `docs/manual/user/web-ui.md` shell description; registry rows FRG-UI-023,
  FRG-PROC-017; delta specs (ui, dev-process).
- Manual impact: `web-ui.md` navigation/shell sections.
- SOUP: none expected (Roboto/FA6 delivery method decided in design.md —
  self-hosted assets, no new runtime dependency beyond static files).
- Security: no new attack surface (static assets self-hosted, no CDN).

## Approval

Covered by the owner's 2026-07-10 standing grant (M4–M7); recorded here per
FRG-PROC-009.
