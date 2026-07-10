# ui delta — m4-design-shell

## MODIFIED Requirements

### Requirement: FRG-UI-002 — Design token layer with the foragerr dark theme

The frontend SHALL centralize all colors, typography, spacing, radii, and
shadows in a design-token layer (CSS variables) consumed by every component —
no hardcoded values in components. The token set SHALL implement the owner's
design: dark warm-neutral surfaces (app background `#202020`, panels/sidebar/
header `#262626`, card `#282828`, raised/menu `#2b2b2b`, input `#1c1c1c`),
one green accent family (`#57b877` primary, `#7fce9a` light/active, tint
backgrounds at 14–16% alpha, dark knockout text on accent), semantic status
hues (owned/complete green, missing/importing amber `#e5a54b`, downloading
blue `#5d9cec`, queued grey), progress-track colors (complete `#2f5d40`,
incomplete `#4a2523`, fill `#57b877`), publisher tint and accent palettes as
data maps, and format-chip colors (TPB blue, Deluxe amber, Omnibus green).
Typography SHALL be Roboto (300/400/500/700, self-hosted) with the design's
scale (page titles 30–33px/700 down to uppercase section labels 10–11px with
letter-spacing), monospace for format labels; icons SHALL be Font Awesome 6
Free, self-hosted. No external font/icon CDN requests SHALL occur at runtime.

#### Scenario: Components consume tokens only

- **WHEN** the frontend source is inspected
- **THEN** colors, font sizes, radii, and shadows in components reference the
  token layer (CSS variables or the exported token/palette maps), and the
  token file is the single place the palette above appears

#### Scenario: No external asset fetches

- **WHEN** the built SPA loads in a browser with the network restricted to
  the application origin
- **THEN** fonts and icons render correctly from self-hosted assets and no
  request leaves the origin

## ADDED Requirements

### Requirement: FRG-UI-023 — Application shell

The SPA SHALL render every screen inside a fixed three-part shell: a 212px
sidebar (logo lockup in a 60px header row; a nav list where each item has
icon, label, and — where meaningful — a live count badge: Comics = library
series count, Activity = queue length, Wanted = count of series with missing
issues (warn style); a SYSTEM section with Settings and System; a footer
status row showing a health indicator and the running version), a 60px
global header (the existing library quick-search input, health and system
icon buttons), and a per-screen toolbar slot above a content region that is
the only scrolling area (no page-level scroll). The active nav item SHALL
carry the accent treatment (inset accent bar, accent icon). The nav SHALL
list only screens that exist — entries for future screens (Calendar,
Creators) appear in the change that ships the screen.

#### Scenario: Shell frames every route

- **WHEN** any existing route (library, series detail, wanted, activity,
  settings, system) is visited
- **THEN** the sidebar, global header, and toolbar slot render with the
  content region scrolling independently, and the active nav item carries
  the accent treatment

#### Scenario: Nav counts are live

- **WHEN** the library gains a series, the queue gains an item, or a series
  gains missing issues while the app is open
- **THEN** the corresponding nav badges update without a page reload (React
  Query + WS invalidation), and the Wanted badge uses the warn style

#### Scenario: Only shipped screens appear in the nav

- **WHEN** the sidebar nav is inspected
- **THEN** every entry routes to an implemented screen, and no entry exists
  for screens not yet shipped
