# design-sync notes — foragerr-frontend

Repo-specific gotchas for future syncs. Companion to `config.json`.

## Build / config shape

- The frontend is an **app, not a library**: no dist entry, no Storybook. The
  converter runs in synth-entry mode — `config.json`'s `entry` deliberately
  points at a nonexistent `frontend/dist/.ds-no-dist.js` so the converter
  (a) walks up from that path to anchor the package at `frontend/`, and
  (b) falls through to synthesizing the entry from `srcDir` (`src/components`).
  Don't "fix" the entry path.
- `srcDir` is `src/components` on purpose: `src/screens` are routed app pages,
  not design-system parts. The component set (~50 incl. the inline SVG icon
  exports from `icons.tsx`) is the design language.
- **All theme CSS + fonts ride the JS bundle**, not cssEntry/tokensGlob/extraFonts:
  `.design-sync/preview-theme.js` (in `extraEntries`) imports
  `frontend/src/theme/global.css` (which imports `tokens.css`), the five
  vendored `@fontsource/roboto` latin weights, and Font Awesome. esbuild
  resolves the CSS `@import`s and inlines woff/woff2 as data URLs into
  `_ds_bundle.css`, so the upload is fully self-contained (matches the app's
  FRG-UI-002 no-CDN posture). `cssEntry` appends raw text without resolving
  `@import`s — do not route theme CSS through it.
- `@fortawesome/.../css/solid.min.css` lists a `.ttf` fallback src that
  esbuild's loader map rejects → `.design-sync/fa-solid.css` is a woff2-only
  stand-in for it (same rules otherwise). Bump it when the FA package bumps.
- `PreviewProvider` / `PreviewData` (`.design-sync/preview-provider.jsx`,
  extraEntries) supply MemoryRouter + react-query + a stub fetcher; they are
  excluded from the component list via `componentSrcMap: null`. The provider
  also wraps every preview in a **dark app-surface div** — foragerr is a
  dark-theme UI and cards render on the harness's white page otherwise
  (translucent tints like the GlobalBanner amber wash out; this was the main
  solo-pass lesson).
- The stub fetcher returns `[]` for list-ish endpoints (regex in
  preview-provider.jsx) and `{}` otherwise; components that need real-looking
  data seed it per-preview via `PreviewData`.

## .d.ts contracts (the design agent's API surface)

- Synth-entry mode alone emits `[key: string]: unknown` stubs for every
  component (no shipped .d.ts tree to extract from). Fix in place:
  `cfg.buildCmd` runs `tsc -p .design-sync/tsconfig.dts.json` (declaration-only
  emit of `frontend/src` → `frontend/dist/types`) followed by
  `.design-sync/gen-types-barrel.mjs` (writes `dist/types/index.d.ts`
  re-exporting every component module), and `frontend/package.json` gained a
  `"types": "dist/types/index.d.ts"` field pointing the extractor at it.
  **Run buildCmd before the converter on every sync** — on a fresh clone
  `dist/types` doesn't exist and skipping it silently regresses all contracts
  to stubs.
- `tsconfig.dts.json` overrides `"types": []` — the app tsconfig pulls in
  vitest/jest-dom type libraries that don't resolve from `.design-sync/`.

## Verification environment

- Playwright: host cache has chromium-1148 + 1228; **latest `playwright` npm
  package pins 1228** — plain `npm i playwright` in `.ds-sync/` works, no
  version archaeology needed (re-check on a future sync).

## Font warns (triaged)

- `[FONT_MISSING] "Font Awesome 6 Brands", "Roboto Mono" (--font-family-mono)`:
  **the real app doesn't ship these either** — tokens.css references a mono
  stack the SPA never vendors, and FA core mentions the Brands family while
  only Solid is imported. The sync mirrors actual app behavior. Flagged to
  Adrian at first-sync close-out; if he wants Roboto Mono for real, vendor it
  in the app first, then re-sync picks it up via preview-theme.js.

## Preview-authoring facts (folded from the first-sync waves)

- **Imports in previews resolve to `window.Foragerr`** — one shared React +
  react-router-dom instance, which is why PreviewProvider's MemoryRouter
  reaches NavLink/useNavigate in chrome components. Never import
  `react-router-dom` directly in a preview (second copy, broken context);
  the barrel doesn't re-export Routes/Route/Outlet, so AppShell's preview is
  the frame with an empty `<Outlet/>` — the honest render.
- **PreviewData is substring-match, first key wins** — order specific keys
  first (`'indexer/schema'` before `indexer`; `entitlements` before
  `sources`). `useSeriesIndex` needs a full paged envelope
  (`{page,pageSize,…,records}`) — a bare `[]` throws. The stub fetcher's
  plural regex misses singular `indexer`, so ProviderSettingsPage genuinely
  needs seeding.
- **Overlay containment recipes (no cardMode overrides needed anywhere):**
  controlled menus take `open`; Popover/ReasonsPopover open via a mount-time
  `.click()` on the trigger (their outside-close listens on `mousedown`, so a
  programmatic `click` doesn't re-close); absolute panels need a
  `position:relative` stage with explicit height; `position:fixed` overlays
  (Modal, ProviderModal) are clipped to the card by a wrapper with
  `transform: translateZ(0); overflow:hidden; height:<enough>` — and `100vh`
  inside still resolves to the real viewport, so give the stage full panel
  height or the footer clips (EditSeries needed 480px).
- **providerKinds configs aren't package exports** — previews inline the kind
  data (chips for ProviderCard; full rowFields/rowDefaults for ProviderModal).
- **Connection store** (zustand singleton, not exported) defaults to
  `connecting` → shell footer shows "reconnecting…" in previews; AppShell
  mounts WebSocketBridge which attempts a real WebSocket, never connects in
  capture, harmless.
- `LogoMarkIcon` is not `<Svg>`-based (viewBox 100×96, default size 20);
  `SpinnerIcon` has no spin animation in the app today — revisit its preview
  if one is added. `PageControls`/`BookTypeBadge` render `null` in edge cases;
  previews pair the null render with a labeled sibling.
- Skipped-as-unstatic states: HeaderQuickSearch open results dropdown,
  LogoutButton in-flight mutation.

## Known render warns

- (none triaged as legitimate yet — populate as they come)

## Re-sync risks

- `preview-theme.js` and `fa-solid.css` silently drift if `main.tsx`'s style
  imports or the FA package change — check both when touching fonts/theme.
- Preview fixtures (PreviewData responses in `.design-sync/previews/*.tsx`)
  inline API shapes from `frontend/src/api/types.ts` (e.g.
  StoreSourceResource) — a backend schema change can stale them without any
  build error; the render check only catches it if the component crashes.
- The dark-surface wrapper lives in cfg-adjacent code (preview-provider.jsx):
  if cards suddenly grade washed-out/white, that wrapper regressed.
