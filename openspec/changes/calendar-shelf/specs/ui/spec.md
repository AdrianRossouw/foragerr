# ui — delta for calendar-shelf

## MODIFIED Requirements

### Requirement: FRG-UI-018 — Weekly pull / calendar view

The UI SHALL provide a Calendar screen at `/calendar` rendering the weekly
release projection (FRG-API-019) as a **date-grouped agenda** — one week at a
time, days as vertical groups, never a 7-column month/week grid. The screen
SHALL provide:

- **Week navigation**: previous / "This Week" / next controls plus a
  human-readable range label; each navigation step re-queries the endpoint
  with the target ISO week (the server holds no navigation state). "This
  Week" SHALL return to the current store-date week from any offset.
- **Scope toggle**: a `Following / All releases` segmented control,
  **defaulting to All releases** — the weekly view doubles as discovery of
  unfollowed books (owner decision; Mylar pull-list philosophy, superseding
  the handoff's Following default). Following shows only entries linked to
  library series (matched or pending-refresh); All releases shows every entry.
  In Following scope, a day with hidden entries SHALL show a
  "+N more titles shipping" note; in All releases scope, a day with followed
  entries SHALL show an "N followed" count.
- **Publisher filter**: a select over the publishers present in the loaded
  week (plus "All publishers"), filtering the agenda client-side.
- **Info banner**: a one-line explanation of the weekly-drop reality with
  the week's followed/total counts, varying by scope.
- **Day groups**: date numeral + weekday + month, an accent bar, and the
  day's entries. Wednesday SHALL carry a "New Comic Day" badge; the current
  date SHALL carry a "Today" badge. Days with no visible entries are omitted.
- **Entry presentation, responsive**: the same entry data SHALL be presented
  in one of two modes selected by viewport width at a **single documented
  crossover of 900px**, shared with the shell's compact mode (FRG-UI-049):
  - **At or above the crossover — shelf rows.** One full-width row per
    entry inside the day's stream, sized by its cover: a **shelf-scale
    cover** of approximately 66×99 CSS px (the stored cover or its
    publisher-tinted spine fallback, FRG-UI-042), then a content block —
    line one is the series title with its issue number (and the debut badge
    per FRG-PULL-008) beside a **fixed-position publisher chip** (color
    swatch + normalized publisher name); line two is the entry's principal
    creators (writer/artist, absent roles omitted); then up to **two
    clamped lines of the stored description** — and the row's state and
    actions right-aligned on a rail. The publisher SHALL be identifiable
    without horizontal scanning: the chip holds a fixed x-position in the
    content block and is never carried only as text trailing the
    variable-length title. The title SHALL render at
    the body base type size, SHALL wrap at word boundaries rather than
    truncate at realistic title lengths, and no action's footprint and no
    other column's content SHALL reduce its measure below approximately 30
    characters per line — the title SHALL therefore carry a definite
    minimum, and the description/creator lines SHALL yield (clamp) to it.
    An entry SHALL occupy no more vertical rhythm than its cover plus
    spacing (approximately 110 CSS px), the deliberate trade of v0.17.0's
    row density for discoverability: the cover and the on-row metadata are
    the browsing surface (owner decision, design session 2).
  - **Below the crossover — quiet cards.** A single column of cards in which
    the title spans the card's full width and wraps at word boundaries, every
    action is an **icon-only** control on an action rail beneath the title
    block (no labelled button competes with the title for horizontal space),
    and the day's gutter folds into an inline day header so the card keeps the
    viewport's width.
  - Both modes SHALL render the same entry data and expose the same actions:
    nothing SHALL be reachable in one mode and unreachable in the other.
- **Derived-state display**: each entry's state SHALL be a projection of the
  entry's `state` (missing/wanted, downloading, downloaded, unmonitored,
  pending-refresh) — never a status stored on the pull entry (D4) — and SHALL
  be rendered as a status indicator that is not shaped or announced as a
  control (FRG-UI-047); in particular the monitor-toggle glyph SHALL appear
  only on entries that carry a real toggle. Not-yet-released entries (store
  date in the future) SHALL be marked as such. That marking MAY be carried
  once per day group rather than per entry — the store date that makes an
  entry unreleased is the day group's own — and SHALL NOT be expressed by
  dimming the entry's text, which is the only carrier of its state.
- **Empty state**: a friendly empty message when the filtered week has no
  entries, distinct from the error state.

The Calendar nav entry lives in the sidebar (shipped-screens rule,
FRG-UI-023). The screen SHALL remain functional when the pull source is
unconfigured or degraded, rendering the metadata-derived half of the
projection (FRG-PULL-001 passthrough). Per-entry actions and the new-series
strip are governed by FRG-PULL-007 and FRG-PULL-008; the monitor toggle's
in-flight behavior by FRG-UI-048.

- **Milestone**: M4
- **Source**: design handoff v2 §4 (calendar.png + dc.html calendar region);
  mylar-feature-surface.md §1 weekly pull; sonarr-architecture.md §7.1
  Calendar; FRG-API-019 (the read surface). Modified in calendar-legibility on
  the owner's report — twice — that the shipped screen is unusable at real
  library density; reshaped to shelf rows in calendar-shelf (owner pick,
  design session 2, 2026-07-30 — the calendar is a discovery surface, so
  cover art and on-row metadata outrank row density).
- **Notes**: Shape decision unchanged: date-grouped agenda, not a Mylar
  pull-list table nor a Sonarr month grid — comics ship in one Wednesday drop,
  a grid piles everything on one column. Scope/publisher filtering stays
  client-side over the fetched week (the endpoint pages at up to 200 rows; the
  client aggregates pages when a week exceeds one page). No iCal feed
  (non-goal).

  The responsive presentation replaces the previous unconditional "release
  cards" wording; the shelf-row mode replaces calendar-legibility's agenda
  rows and retires that change's 36px density ceiling. The 900px crossover is derived from the screen's own
  geometry, not a device table: fixed chrome to the left of the entry area
  (sidebar, screen padding, day gutter, gap, stream border and padding) plus a
  row's own cover and action cluster leave a row about 396px to divide between
  the title and the meta at 900px — enough for the title's ~30-character floor
  with the meta yielding, and not enough for both at their natural widths,
  which is why the floor is a definite track minimum rather than a residual.
  At 840px the same arithmetic leaves ~336px, while a full-width two-line card
  at that width carries roughly 55 characters, so the card genuinely wins
  below the crossover. The crossover also sits above the width at which the
  shipped `minmax(228px, 1fr)` grid stops fitting two columns (~840px
  viewport), so compact mode takes over before the wide grid's own fit fails
  and no width is served badly by both modes.

#### Scenario: Default load shows the current week's ALL releases

- **WHEN** the Calendar screen loads with no navigation state
- **THEN** it requests the current store-date week (no `week` param needed)
  and renders every entry — followed and unfollowed alike — grouped by day
  with the range label, marking Wednesday "New Comic Day" and the current
  date "Today", so the week reads as a discovery surface first

#### Scenario: Week navigation is parameterised and reversible

- **WHEN** the user clicks next, then next, then "This Week"
- **THEN** each click re-queries the endpoint with the correct target ISO
  week (+1, +2, then current), the range label follows, and no server-side
  navigation state is involved

#### Scenario: Following scope narrows to library entries

- **WHEN** the user switches the scope toggle to "Following" on a week
  containing both linked and unmatched entries
- **THEN** only entries linked to library series remain, days show the
  "+N more titles shipping" note for what was hidden, and switching back to
  All releases restores the full week with its "N followed" day counts

#### Scenario: Derived state is projected, never stored

- **WHEN** a linked entry's card renders and the underlying issue's
  monitored flag or queue presence changes
- **THEN** the card's state indicator reflects the new derived state after the
  relevant query invalidation, and no pull-entry field was written to effect
  the change

#### Scenario: Degraded pull source still renders the local projection

- **WHEN** the pull source is unconfigured or its last fetch failed
- **THEN** the Calendar still renders watched-series issues store-dated in
  the viewed week with correct derived state, and no error state replaces
  the agenda

#### Scenario: A wide viewport renders shelf rows with fixed-position publishers

- **WHEN** the Calendar renders a week at or above the 900px crossover,
  including an entry whose title is long enough to have truncated in the card
  grid, on a viewport wide enough that inline meta would trail far from the
  title
- **THEN** each entry is a single full-width shelf row (shelf-scale cover,
  title + issue with the publisher chip at its fixed position, creators line,
  clamped description, right-aligned state/actions), the title wraps at word
  boundaries with no mid-word break and no ellipsis at a measure of at least
  approximately 30 characters, and the publisher chip's x-position does not
  vary with the title's length — the eye finds every row's publisher at one
  place without scanning to the line's end

#### Scenario: A narrow viewport renders quiet cards with an icon rail

- **WHEN** the Calendar renders below the crossover
- **THEN** entries render as a single column of cards in which the title spans
  the full card width and wraps at word boundaries, every action — including
  the add affordance — is an icon-only control on the rail beneath the title
  block with no labelled button in the title's row, and the day's gutter is an
  inline header rather than a fixed column

#### Scenario: Neither mode hides an action the other offers

- **WHEN** the same week is rendered on either side of the crossover
- **THEN** each entry exposes the identical set of actions and the identical
  entry data in both modes, differing only in placement and in whether an
  action's label is rendered as text

#### Scenario: A dense day browses by cover

- **WHEN** a single day of roughly 60 entries is rendered at or above the
  crossover
- **THEN** every entry renders its shelf-scale cover and on-row metadata with
  no entry exceeding approximately 110 CSS px of vertical rhythm for a
  single-line title (measured in the browser-driven tier), covers below the
  viewport load lazily, and the frame never scrolls sideways — the day is a
  browsable shelf rather than a table, by design

### Requirement: FRG-UI-042 — Calendar covers and enrichment detail

The Calendar screen (FRG-UI-018) SHALL render each pull entry's stored
cover as a lazy-loaded image served same-origin through the
authenticated cover proxy (FRG-META-021) — at shelf scale
(approximately 66×99 CSS px) at or above the layout crossover, card
scale below it — falling back to the
publisher-tinted spine when the cover is absent or fails to load —
never a broken image. The shelf row SHALL surface the entry's
principal creators (writer/artist) and up to two clamped lines of the
stored description inline; an entry detail surface SHALL expose the full stored
enrichment — description, creators (role and name), characters, and
UPC — omitting absent fields. Publisher tint and accent resolution
SHALL match the feed's publisher names by normalized comparison
(corporate suffixes such as "Comics", "Studios", "Entertainment",
"Publishing" fold away before the palette lookup), and a publisher
outside the named palette SHALL derive a stable, deterministic accent
hue distinct from the brand accent — every publisher is
distinguishable at a glance, on the Calendar and on every other
surface resolving through the shared palette helpers. Rendering pull imagery and enrichment
SHALL issue no ComicVine requests: the Calendar's imagery is
budget-free by design (FRG-META-022's lanes are not involved).

- **Milestone**: M11 (m11-discovery-surface); reshaped to shelf scale
  with on-row enrichment and normalized publisher resolution in
  calendar-shelf.
- **Source**: rig finding #17 (Calendar covers never built) + the
  2026-07-23 cover-URL facts; FRG-PULL-011 supplies the stored data.
- **Notes**: First cover-proxy consumer outside the add/import
  pickers, via the existing same-origin URL helper. Lazy loading keeps
  concurrent proxy fetches bounded to the viewport; the browser cache
  honors the proxy's cache headers. Detail surface form (popover vs
  expando) is an implementation call.

#### Scenario: Covers render through the authenticated proxy

- **WHEN** the viewed week contains entries with stored cover URLs
- **THEN** each card's thumbnail loads lazily from the same-origin
  proxy endpoint with the cover URL as its encoded parameter, under
  the unchanged self-contained CSP

#### Scenario: Absent or failing covers degrade to the spine

- **WHEN** an entry has no stored cover, or its proxy fetch errors
- **THEN** the card renders the existing publisher-tinted spine with
  no broken-image artifact

#### Scenario: Entry detail exposes enrichment, omitting the absent

- **WHEN** the user opens an entry's detail surface for an entry with
  a description and creators but no characters or UPC
- **THEN** the description and creators (with roles) render and the
  absent fields are omitted rather than shown empty

#### Scenario: A rendered week spends no ComicVine budget

- **WHEN** a week's Calendar renders covers and enrichment for its
  entries
- **THEN** no ComicVine API request is issued on behalf of pull
  imagery or enrichment


#### Scenario: The shelf row carries creators and a clamped description

- **WHEN** a week renders at or above the crossover with an entry storing
  creators and a long description
- **THEN** the row shows the writer/artist line and at most two lines of
  description (clamped, full text in the detail surface), and an entry
  missing those fields simply omits the lines — never empty placeholders

#### Scenario: Live publisher names resolve to their palette colors

- **WHEN** the feed delivers publishers as "Marvel Comics", "DC Comics",
  or "BOOM! Studios"
- **THEN** their chips and spines carry the Marvel/DC/BOOM! palette
  colors (normalized match), and a publisher with no palette entry
  renders a stable derived hue that is not the brand accent
