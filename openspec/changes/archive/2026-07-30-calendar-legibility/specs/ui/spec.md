# ui — delta for calendar-legibility

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
  - **At or above the crossover — agenda rows.** One full-width row per
    entry inside the day's stream: a fixed-size cover thumbnail (the stored
    cover or its publisher-tinted spine fallback, FRG-UI-042), the series
    title as the row's primary column taking all width remaining after the
    thumbnail, meta and actions, the issue number · publisher · state meta
    after it, and the row's actions right-aligned. The title SHALL render at
    the body base type size, SHALL wrap at word boundaries rather than
    truncate at realistic title lengths, and no action's footprint and no
    other column's content SHALL reduce its measure below approximately 30
    characters per line — the title's column SHALL therefore carry a definite
    minimum, and the meta column SHALL yield to it. Rows SHALL be dense
    enough that an entry whose title fits one line occupies **no more than 36
    CSS px of vertical rhythm**, so a day of roughly 60 entries reads in
    roughly two viewport heights rather than the four the card grid produced.
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
  library density.
- **Notes**: Shape decision unchanged: date-grouped agenda, not a Mylar
  pull-list table nor a Sonarr month grid — comics ship in one Wednesday drop,
  a grid piles everything on one column. Scope/publisher filtering stays
  client-side over the fetched week (the endpoint pages at up to 200 rows; the
  client aggregates pages when a week exceeds one page). No iCal feed
  (non-goal).

  The responsive presentation replaces the previous unconditional "release
  cards" wording. The 900px crossover is derived from the screen's own
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

#### Scenario: A wide viewport renders agenda rows whose titles survive

- **WHEN** the Calendar renders a week at or above the 900px crossover,
  including an entry whose title is long enough to have truncated in the card
  grid
- **THEN** each entry is a single full-width row (thumbnail, title column,
  issue · publisher · state meta, right-aligned actions), the title renders at
  the body base type size and wraps at word boundaries with no mid-word break
  and no ellipsis, and its measure is not reduced below approximately 30
  characters (measured in the browser-driven tier at the crossover width) by
  any action present on the row, by the length of the publisher name beside
  it, or by any other column — the meta's own text ellipsises instead, and the
  frame does not scroll sideways to make the measure fit

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

#### Scenario: A dense day stays scannable

- **WHEN** a single day of roughly 60 entries is rendered at or above the
  crossover
- **THEN** every entry whose title fits one line occupies no more than 36 CSS
  px of vertical rhythm — thumbnail, controls, padding and separator included
  (measured in the browser-driven tier) — so the day reads in roughly two
  viewport heights rather than the four the card grid produced; a title long
  enough to wrap adds its own extra line and nothing else

## ADDED Requirements

### Requirement: FRG-UI-047 — Status indicators are never shaped like controls

The UI SHALL NOT render a non-interactive status indicator in the shape of a
control. Wherever derived or observed state is displayed:

- the indicator SHALL be **visually** distinct from the controls on the same
  surface — a dot, chip, or text token rather than an icon sitting in a
  control's hit box — and SHALL NOT reuse a glyph that, on that same surface,
  denotes an actionable control;
- it SHALL carry no control affordances: no pointer cursor, no hover
  state that mimics a control's, no focus ring, and it SHALL NOT be focusable;
- it SHALL be **semantically** a status, not a control: no `button` role, no
  `aria-pressed`, and its meaning SHALL be available as text (accessible name
  or adjacent label) so assistive technology announces state rather than an
  operable element.

Conversely, a control that IS present SHALL be a real button: keyboard
reachable, carrying a visible `focus-visible` outline, and presenting a target
of at least 24 × 24 CSS pixels (the WCAG 2.5.8 floor).

On the Calendar specifically, the monitor bookmark glyph SHALL appear **only**
on entries that carry a real monitor toggle (FRG-PULL-007's linked entries);
every other entry's state SHALL render as a status indicator meeting the rules
above — including the wanted state, which SHALL NOT be drawn as the filled
accent bookmark that denotes an active toggle.

- **Milestone**: B (calendar-legibility)
- **Source**: the owner's report that the Calendar's monitor button cannot be
  clicked — the icon was a decorative `<span>` drawing the toggle's own glyph,
  filled and accent-toned in the wanted state, on entries that have no toggle.
  Generalised beyond the Calendar because the failure mode is a class, not one
  screen's bug.
- **Notes**: This is a UI-layer honesty rule and changes no behavior on the
  server: it constrains how state is *drawn and announced*, never which
  actions exist (FRG-PULL-007 continues to govern that). The 24px target floor
  is scoped to the surfaces a change touches; axe-core does not test WCAG
  2.5.8, so the floor is verified by measuring rendered geometry in the
  browser-driven tier (FRG-PROC-019's harness) rather than by the automated
  ruleset. Bringing every existing ~21px icon button across the app to the
  floor is separate work.

#### Scenario: An entry with no real toggle shows a status, not a button

- **WHEN** the Calendar renders an entry that has no linked library issue —
  unmatched, a new-series debut, or pending-refresh — in any derived state
- **THEN** its state renders as a status indicator that is not a button: not
  focusable, no `button` role, no `aria-pressed`, no pointer cursor and no
  control hover treatment, and it does not draw the monitor toggle's bookmark
  glyph (filled or hollow)

#### Scenario: A real control is unmistakably a control

- **WHEN** the Calendar renders an entry that does carry a monitor toggle
- **THEN** the toggle is a real button element with `aria-pressed` reflecting
  the monitored state, reachable in keyboard order, showing a visible
  `focus-visible` outline when focused, and presenting a target of at least
  24 × 24 CSS pixels

#### Scenario: Assistive technology hears state as state

- **WHEN** assistive technology walks a day's entries containing both linked
  and unlinked entries
- **THEN** every status indicator is announced as text or status and never as
  an operable element, and the number of button elements exposed per entry
  equals the number of actions that entry actually has

#### Scenario: Touch targets meet the floor on the surfaces this change touches

- **WHEN** the calendar's controls and the responsive chrome's toggle are
  measured in a real browser at both sides of the crossover
- **THEN** every one presents a target of at least 24 × 24 CSS pixels,
  including the icon-only controls on the narrow-viewport action rail

### Requirement: FRG-UI-048 — In-flight feedback for the calendar's monitor toggle

The Calendar's monitor toggle SHALL acknowledge activation immediately rather
than appearing dead until a refetch lands. On activation the control SHALL
render the **requested** monitored state at once in a busy presentation and
SHALL suppress further mutations until the in-flight one settles. On success
the optimistic state SHALL be replaced by the re-projected derived state
(query invalidation), so no optimistic value outlives the server's
confirmation. On failure the control SHALL return to the entry's true state
**and** the failure SHALL be surfaced to the operator per the actionable-
guidance rules (FRG-UI-030, FRG-UI-033) — never a silent revert that reads as
a click that did nothing.

- **Milestone**: B (calendar-legibility)
- **Source**: the shipped toggle has no pending state, unlike the Search
  action beside it, which disables while its command runs; a working click
  therefore looks dead and invites a second click.
- **Notes**: The mutation itself is unchanged — the canonical single-issue
  monitored update (FRG-API-004) via the existing hook, with the same
  invalidations. This requirement is about the control's own presentation and
  duplicate-suppression, so it adds no request and no pull-side write (D4
  stands).

#### Scenario: Activation is acknowledged at once

- **WHEN** the operator activates the monitor toggle on a linked entry and the
  mutation has not yet settled
- **THEN** the control immediately renders the requested monitored state in a
  busy presentation, and activating it again while in flight issues no second
  mutation

#### Scenario: Success settles to the projection, not the optimistic guess

- **WHEN** the mutation succeeds
- **THEN** the optimistic state is replaced by the entry's re-projected derived
  state after invalidation, so the entry never keeps a monitored value the
  server did not confirm

#### Scenario: Failure reverts visibly and says so

- **WHEN** the mutation fails
- **THEN** the control returns to the entry's true monitored state and the
  failure is surfaced to the operator as actionable guidance, rather than the
  control silently snapping back

### Requirement: FRG-UI-049 — Responsive application chrome below the compact crossover

The shell's sidebar SHALL NOT hold a fixed column of the viewport below the
compact crossover — **900px** viewport width, the same value the Calendar's
presentations switch on (FRG-UI-018). Below that width it SHALL collapse to an
off-canvas drawer: hidden by default, opened by a labelled toggle in the
global header, dismissible by the Escape key, by the backdrop, and by
choosing a nav item,
with focus moved into the drawer on open and returned to the toggle on close;
and the content region SHALL span the full viewport width. At or above the
crossover the frame SHALL render exactly as FRG-UI-023 specifies, with no
toggle present. The nav's items, count-badge policy, shipped-screens rule and
the single-scrolling-region rule (all FRG-UI-023) are unaffected — only the
chrome's placement changes with width.

- **Milestone**: B (calendar-legibility)
- **Source**: at phone-width viewports the fixed 212px sidebar leaves under
  200px of content region once a screen's own gutters are subtracted, clipping
  header text and thumbnails. Scoped into calendar-legibility because the
  Calendar's narrow-viewport presentation cannot be built or verified while the
  chrome occupies the viewport it is meant to fit.
- **Notes**: Written as the narrow-viewport qualifier of FRG-UI-023 rather
  than a restatement of it, because FRG-UI-023's remaining content is
  viewport-independent and restating it wholesale would risk transcription
  error for no gain. One crossover value serves both the chrome and the
  Calendar so the two cannot disagree; it is recorded once in the layout token
  layer as the single source for both media queries. No new dependency and no
  layout framework: a drawer, a backdrop, and a toggle.

#### Scenario: A narrow viewport frees the content region

- **WHEN** the app renders below the crossover
- **THEN** the sidebar occupies no fixed column, the content region spans the
  full viewport width, and a labelled nav toggle is present in the global
  header

#### Scenario: The drawer is keyboard-operable and dismissible

- **WHEN** the operator opens the drawer from the keyboard below the crossover
- **THEN** focus moves into the drawer, Escape closes it and returns focus to
  the toggle, and activating a nav item navigates and closes the drawer

#### Scenario: A wide viewport is unchanged

- **WHEN** the app renders at or above the crossover
- **THEN** the sidebar renders as the persistent column of FRG-UI-023 with no
  toggle present, and the nav's items and badges are unchanged
