# foragerr UI conventions

foragerr is a **dark-theme, Sonarr-shaped** comic library manager. Every design
must sit on the dark surface system — there is no light mode.

## Setup

Most components are self-contained leaves: import and render, no wrapper
needed. The app-chrome components that read live data — `AppShell`, `Sidebar`,
`GlobalBanner`, `HeaderQuickSearch`, `LogoutButton` — call router and
data-fetching hooks and will throw outside context. Wrap any design using them
in `PreviewProvider`, and seed what they show with `PreviewData`:

```jsx
<PreviewProvider>
  <PreviewData responses={{ sources: [{ id: 1, type: 'humble', name: 'Humble Bundle',
      connection_state: 'expired', auto_sync: false, last_sync_status: null, settings: {} }] }}>
    <GlobalBanner />
  </PreviewData>
</PreviewProvider>
```

`PreviewData`'s `responses` keys match by substring against the request path
(`sources`, `wanted`, `queue`, …); unmatched paths resolve to empty data.

## Styling idiom: CSS custom-property tokens, no utility classes

Components carry their own styles (CSS modules, already in the bundle). Style
YOUR layout glue with inline styles or your own CSS reading the token
vocabulary — **never hardcode a hex, font, or shadow**; every value exists as
a `var(--*)` token:

- **Surfaces** (dark, warm-neutral): `--surface-page` (app bg), `--surface-chrome`
  (header/toolbar), `--surface-sidebar`, `--surface-card` / `--surface-card-hover`,
  `--surface-menu`, `--surface-input`, `--surface-overlay`, `--surface-hover` /
  `--surface-active`, borders `--surface-border` / `-soft` / `-hard`.
- **Accent** (the one brand green): `--color-accent`, `--color-accent-light`,
  `--color-accent-hover`, `--color-accent-tint`, `--color-accent-selected-bg`,
  text-on-accent `--color-accent-contrast`.
- **Status**: `--color-success`, `--color-warning`, `--color-danger`,
  `--color-info` (each with `-text` / `-tint` variants for success/warning/info),
  progress `--color-progress-fill` / `-complete` / `-incomplete`.
- **Text**: `--text-primary`, `--text-secondary`, `--text-muted`, `--text-faint`,
  `--text-bright`, `--text-on-accent`.
- **Type**: `--font-family-base` (Roboto, self-hosted), sizes `--font-size-xs/sm/base/lg/heading/page-title/section-label`,
  weights `--font-weight-light/normal/medium/bold`.
- **Geometry**: `--spacing-xs/sm/md/lg/xl`, `--radius-sm/md/lg/pill`,
  `--shadow-card`, `--shadow-menu`, `--shadow-overlay`,
  layout `--layout-sidebar-width`, `--layout-header-height`, `--layout-toolbar-height`,
  `--layout-content-max-width`, icons `--icon-size-sm/md/lg`.

Icons: use the bundled inline-SVG set (`GridIcon`, `TableIcon`, `SearchIcon`,
`PlusIcon`, `RefreshIcon`, `TrashIcon`, `CheckIcon`, `CloseIcon`, `SortIcon`,
`FilterIcon`, …) — they draw in `currentColor` and take a `size` prop. Font
Awesome solid classes (`<i className="fa-solid fa-…" />`) also render.

## Where the truth lives

Read `styles.css` → `_ds_bundle.css` (token definitions at top, then component
styles) before inventing any style. Each component's props contract is its
`.d.ts`; usage examples are in its `.prompt.md`.

## Idiomatic page skeleton

```jsx
<div style={{ background: 'var(--surface-page)', color: 'var(--text-primary)',
    fontFamily: 'var(--font-family-base)', minHeight: '100vh' }}>
  <Toolbar title="Comics" actions={<>
    <ToolbarButton icon={<RefreshIcon />} label="Refresh" onClick={() => {}} />
    <ToolbarSeparator />
    <ToolbarButton icon={<GridIcon />} label="Posters" active onClick={() => {}} />
  </>} />
  <main style={{ padding: 'var(--spacing-lg)', display: 'flex', gap: 'var(--spacing-sm)' }}>
    <Chip>DC Comics</Chip>
    <Chip tone="success">Downloaded</Chip>
    <Chip tone="accent">Monitored</Chip>
  </main>
</div>
```
