# calendar-legibility — the Calendar at real-library density

## Why

The owner has reported the shipped Calendar as unusable twice while working
their own full library. The complaints are specific, and reading the screen
against them turns up four separate defects rather than one taste
disagreement:

1. **The monitor control is a lie on most cards.** Only an entry linked to an
   existing library issue renders a real toggle button. Every unmatched entry,
   every new-series debut, and every pending-refresh entry instead renders a
   derived-state *glyph*: a non-interactive `<span>` drawing the **same
   bookmark icon at the same size** as the real toggle, with no cursor, no
   hover, no focus ring, and no button semantics. In the wanted state that
   glyph is drawn **filled, in the accent colour** — pixel-for-pixel the
   active-toggle treatment. Because the scope toggle defaults to All releases,
   most of what the operator sees on first load is fake buttons. The owner's
   complaint is literally "I'm not sure why I can't just click on the monitor
   button" — the affordance promised a control and there was none.
2. **The Add button's footprint squeezes the title out of existence.** `Add`
   is a labelled button (icon + word + border + padding), roughly three times
   the width of an icon button, sitting in the same fixed action cluster
   inside cards whose grid minimum is 228px. Cover, gaps, and that cluster
   leave the title column around 70px, so a long title shatters mid-word
   across its two clamped lines even after the wrap fix that preceded this
   change. The title — the one thing the screen exists to let you scan — is
   the element that yields.
3. **No feedback on the real toggle.** The monitor mutation has no pending or
   optimistic state, unlike the Search action beside it, which disables while
   its command runs. A successful click therefore looks dead until a refetch
   lands, so the operator clicks again.
4. **The shell never yields either.** The sidebar holds a fixed 212px column
   at every viewport width. On a phone-width viewport that leaves under 200px
   of content region once the calendar's own 114px of day gutter and stream
   chrome is subtracted; header text and thumbnails clip. This is not
   separable from the calendar work: a narrow-viewport presentation cannot be
   built or tested while the chrome eats the viewport it is meant to fit.

Density is the through-line. A single-issue drop day at real library scale is
a long day, and the current card grid spends most of its pixels on card
chrome and action buttons rather than on titles — a day of ~60 entries runs to
roughly four viewport heights of near-illegible cards.

## What Changes

### The layout decision (settled by the owner, not open)

**Agenda rows on desktop; the quiet-card grid as the narrow-viewport
fallback**, switching at a single documented crossover of **900px** viewport
width.

- **At or above 900px — agenda rows.** One compact row per entry: a
  fixed-size cover thumbnail, the series title as the row's primary column
  taking all remaining width and never truncating at realistic title lengths,
  the issue-number · publisher · state meta after it, and the actions
  right-aligned. This is the Sonarr/Radarr calendar idiom the project's design
  school already points at, and it is what makes density possible: the target
  is that a ~60-entry day reads in roughly one and a half viewport heights,
  not four.
- **Below 900px — the quiet card.** The existing card grid, one column, with
  every action reduced to an icon-only control on a bottom action rail beneath
  the title block, so the title gets the card's full width and wraps at word
  boundaries. The day's 72px gutter also folds into an inline day header at
  this width, because a fixed gutter is 114px of chrome the narrow viewport
  cannot spare.

**Why 900px.** It is the width at which the agenda row stops being the better
presentation, derived from the existing geometry rather than picked from a
device table. Chrome to the left of the entry area is fixed: 212px sidebar +
48px screen padding + 72px day gutter + 20px gap + 22px stream border and
padding = 374px. A row must then hold ~19px card padding, a 36px cover, an
11px gap, the meta column (~150px), and an action cluster of three
minimum-size targets (~80px) — about 307px — before the title gets anything.
So the title's measure on a row is roughly *viewport − 681px*: ~219px (≈30
characters) at 900px, ~40 characters at 1000px, and only ~21 characters at
840px. A quiet card at that same narrow width gives the title the card's full
209px across two wrapped lines — roughly 55 characters — so below ~900px the
card genuinely wins and above it the row does.

900px also sits **above** the point where the existing `minmax(228px, 1fr)`
grid stops fitting two columns (that happens at ~840px viewport: 228 × 2 + 10px
gap = 466px of entry area). Choosing the crossover above that boundary means
compact mode takes over *before* the desktop grid's own fit fails, leaving no
dead zone in which neither presentation works. The value is also the one the
shell's sidebar collapses at, so the app has exactly one compact-mode
crossover rather than two that can disagree.

### Requirements

- **MODIFIED `FRG-UI-018`** (complete restatement): the Calendar's entry
  presentation becomes the two responsive modes above with the 900px
  crossover, a stated density target, and a title that keeps its measure. The
  requirement is *modified* rather than supplemented because its shipped text
  mandates "release cards" in the day-group bullet — an added requirement
  describing agenda rows would sit beside an active requirement contradicting
  it, which is exactly the drift the spec-as-source-of-truth rule exists to
  prevent. Everything else in FRG-UI-018 (week navigation, scope toggle and
  its All-releases default, publisher filter, info banner, derived-state
  projection, empty state, degraded-source behavior) is restated unchanged,
  and all five of its existing scenarios are restated verbatim in substance.
- **ADDED `FRG-UI-047` — status is never shaped like a control.** A
  non-interactive status indicator SHALL be visually and semantically distinct
  from a control on the same surface: no button hit box, no hover or focus
  affordance, not focusable, no button role or pressed state, and it SHALL NOT
  reuse the glyph that denotes an actionable control on that same surface. On
  the Calendar the bookmark glyph therefore appears **only** where a real
  monitor toggle exists; every other entry's state renders as a status chip.
  The requirement also pins the control side: real controls carry a
  focus-visible outline and present at least a 24 × 24 CSS-px target.
- **ADDED `FRG-UI-048` — in-flight feedback on the calendar's monitor
  toggle.** Activation immediately shows the requested state in a busy
  presentation, suppresses duplicate mutations while in flight, reverts
  visibly with a surfaced failure rather than silently, and settles to the
  re-projected derived state.
- **ADDED `FRG-UI-049` — responsive application chrome.** Below the 900px
  crossover the sidebar collapses to a keyboard-operable off-canvas drawer
  behind a labelled header toggle and the content region spans the viewport;
  at or above it, FRG-UI-023's frame renders unchanged.

**Scoping the sidebar in is deliberate.** The narrow-viewport fallback is
untestable while a fixed 212px column occupies half a phone-width viewport, so
splitting it into a sibling change would mean shipping a card mode nobody can
verify. FRG-UI-049 is written as the narrow-viewport qualifier of FRG-UI-023
rather than as a restatement of it: FRG-UI-023's other content (nav items,
badge policy, shipped-screens rule, the single scrolling region) is unrelated
to viewport width, and restating it wholesale would risk transcription error
for no gain. If the owner prefers the shell's viewport behavior to live inside
FRG-UI-023 itself, that is a MODIFIED restatement instead — say so at
approval and the delta changes shape, not scope.

## Open question for the owner (FRG-PROC-009)

One interaction decision is deliberately **not** made here, because it changes
what a click *does* rather than how the screen looks. The wording of the
question, for the record:

> **On a calendar entry with nothing in the library behind it yet, what should
> the bookmark affordance do?**
>
> **(a) Nothing — there is no bookmark there at all.** Status becomes a chip or
> dot that is visually and semantically not a control, the bookmark renders
> only where a real monitor toggle exists, and an unmatched entry keeps
> **Add** as its single primary action. Honest and minimal: every button on
> the screen does something, and nothing hides a multi-step action behind a
> small icon. Cost: wanting an unfollowed book stays two steps — Add the
> series, then monitor the issue.
>
> **(b) The bookmark becomes a real one-tap "follow".** On an unmatched entry,
> activating it adds the series *and* monitors that issue in one action. This
> is what the thumb currently expects, and it is the fastest path from "I want
> this" to "foragerr is looking for it". Cost: a small icon triggers a
> two-effect mutation that creates a library record — it needs a confirm or an
> undo of its own, it can partially fail (series added, monitor not set), and
> it widens FRG-PULL-007, which today states that unlinked entries expose no
> issue actions at all.
>
> **(a) is the floor either way** — a decorative glyph impersonating a button
> is a defect regardless of what we decide, and this change fixes it.
> **(b) is an optional addition on top of (a)**, and if you want it, it is a
> requirement of its own (with its own undo story and a FRG-PULL-007 delta),
> not a tweak to the ones proposed here.

**Recommendation: (a) now, (b) only if you want the shortcut badly enough to
pay for a confirm/undo path.**

## Capabilities

### New Capabilities

None — extensions of the existing `ui` capability.

### Modified Capabilities

- `ui`: MODIFIED FRG-UI-018 (responsive entry presentation, agenda rows +
  quiet-card fallback, density and title-measure floors; complete
  restatement), ADDED FRG-UI-047 (status indicators are not control-shaped),
  ADDED FRG-UI-048 (in-flight monitor-toggle feedback), ADDED FRG-UI-049
  (responsive application chrome).

## Impact

- **Frontend only.** `CalendarScreen.tsx` and `CalendarScreen.module.css`
  (the row/card presentations behind one crossover, the status chip replacing
  the control-shaped glyph, the icon rail, the inline day header, minimum
  target sizes, the toggle's in-flight state), `AppShell.tsx` /
  `AppShell.module.css` and the header (the off-canvas drawer and its toggle),
  and a shared minimum-target treatment in the token layer.
- **No backend change.** No new endpoint, no new field, no migration, no
  change to what the weekly-pull projection returns; the pull surface stays
  read-only and derived state stays derived.
- **No dependency change** — no SOUP register delta (FRG-PROC-012).
- **Security (FRG-PROC-006)**: no new attack surface. No listener, no parser
  of untrusted input, no credential handling, no outbound integration; the
  change moves and re-labels existing client-side controls over data the
  screen already renders. No STRIDE or risk-register delta expected. Review
  gate: medium tier (a presentation change across two shared shell files plus
  a screen), with an accessibility angle carrying the a11y assertions below.
- **Accessibility.** Explicit and testable, not incidental:
  - real controls carry a `focus-visible` outline and reachable keyboard
    order, including inside the narrow-viewport icon rail and the sidebar
    drawer (focus moves in on open, returns to the toggle on close, Escape
    dismisses);
  - a status indicator is **never** announced as a control — no `button`
    role, no `aria-pressed`, not focusable; its state is available as text;
  - **tap targets**: the calendar's icon buttons are currently ~21px (a 13px
    glyph in 4px padding), under the WCAG 2.5.8 24 × 24 CSS-px floor. **This
    change fixes that for the surfaces it touches** — the calendar's controls
    and the new chrome toggle/drawer — because the narrow-viewport rail is
    thumb-driven and it would be dishonest to ship a mobile fallback under the
    floor. An app-wide sweep of every ~21px icon button on other screens is a
    **non-goal** here and needs its own change; axe-core does not test 2.5.8,
    so the floor is verified by measuring bounding boxes in the browser-driven
    tier rather than assumed.
- **Manual impact (FRG-PROC-011)**: `docs/manual/user/web-ui.md` — the
  **Calendar** section (entry presentation at both widths, what the monitor
  affordance is and where it exists, what a status indicator means) and the
  **The shell** section, whose "the sidebar never moves" sentence stops being
  true below the crossover. No admin-manual or README impact: no
  configuration, deployment, or feature-set fact changes.

## Non-goals

- **No new data or API surface.** No endpoint, field, query parameter, or
  migration; nothing the weekly-pull projection returns changes, and no
  pull-side status is written (the derived-state rule stands).
- **No calendar redesign beyond these defects.** Week navigation, the scope
  toggle and its All-releases default, the publisher filter, the debuts
  filter, the info banner, covers and the enrichment detail expando, the
  degraded-source notice and the empty state all keep their shipped behavior
  and wording.
- **Read-only series are already out of the calendar week.** A sibling change
  settled that they no longer appear at all rather than appearing as
  uncontrollable rows. That is upstream behavior this change consumes, not a
  decision to re-litigate.
- **No one-tap follow on unmatched entries** unless the owner picks option
  (b) above; it would be a separate requirement with its own undo story and a
  FRG-PULL-007 delta.
- **No app-wide tap-target or responsive sweep.** Only the calendar and the
  shell chrome are brought to the 24px floor and to responsive behavior; the
  other screens' controls and layouts are untouched.
- **No new breakpoint vocabulary.** One crossover value, shared by the
  calendar and the chrome; no tablet tier, no container queries, no layout
  framework.

## Approval

Approved 2026-07-30 under authority the owner delegated in-session ("you can
approve the spec"), recorded by the orchestrator rather than by the owner's
own reading of this text. The owner set the layout direction themselves —
agenda rows on desktop with the quiet card as the narrow fallback, chosen from
three illustrated variants — and delegated the remaining decisions.

Decisions taken with that authority:

1. **The open bookmark question resolves to option (a).** A status indicator
   stops being control-shaped, and the bookmark renders only where a real
   monitor toggle exists; an unmatched entry keeps Add as its single primary
   action. Option (b), one-tap follow, is not in scope: it hides a two-effect
   mutation that creates a library record behind a small icon, needs its own
   undo path, and would amend FRG-PULL-007, which currently states that
   entries without a linked issue expose no issue actions. (a) is also the
   only option that resolves the defect rather than redecorating it. If the
   two-step path proves annoying in daily use, (b) becomes its own change with
   its own undo story.
2. **The sidebar crossover stays in this change** (FRG-UI-049 as the
   narrow-viewport qualifier of FRG-UI-023, not a restatement of it). A
   narrow-viewport presentation cannot be verified while fixed chrome occupies
   half the viewport it must fit.
3. **The 24 x 24 CSS-px target floor applies to the surfaces this change
   touches**, not app-wide. Shipping a thumb-driven rail below the floor would
   be dishonest; sweeping every other screen is a separate change.

Implementation may proceed on these terms.

### Amendment — FRG-UI-018's density figure (recorded by the orchestrator)

The "~1.5 viewport heights at 60 entries" figure this proposal set is
**unreachable while FRG-UI-047's 24px target floor holds**, so the change as
first written contradicted itself: a 24px-minimum control plus the row's
padding and separator is a 29px band before any thumbnail, and 60 × 29 is 1.9
raw viewport heights at a 900px-tall viewport. The figure was chosen before the
target floor existed.

FRG-UI-018's density clause and its dense-day scenario are therefore restated
as an **absolute per-entry bound — no more than 36 CSS px of vertical rhythm
for an entry whose title fits one line** — with the consequence stated as
"roughly two viewport heights rather than four". A per-entry bound is
measurable in the browser tier without depending on viewport height, and the
one-line qualifier keeps the bound honest against the same requirement's
never-truncate rule: a wrapped title adds a line and nothing else. Measured
after the row thumbnail shrank from 20 × 30 to 16 × 24, a single-line row band
is **29px**, so 60 entries occupy ~1.9 raw viewport heights.

Two smaller spec corrections land with it, both consequences of measuring the
shipped screen rather than deriving it:

- **The title's measure is a floor, not a residual.** The meta column sized to
  its own content, which is unbounded (publisher name + state chip + the
  not-yet-released token), so the flexible title column was the one the grid
  sacrificed: 23 characters on a typical row at the crossover and 7 on a
  future-dated one. FRG-UI-018 now requires a *definite* minimum on the title's
  column with the meta yielding to it, and names the browser tier as where the
  measure is checked.
- **The not-yet-released marking may be carried once per day group, and may not
  be expressed by dimming text.** Per entry it is a ~110px nowrap token in the
  same track that starves the title, and the store date that makes an entry
  unreleased belongs to the whole day group anyway. The shipped
  whole-entry `opacity: 0.72` also pushed the meta text to 3.68:1 and the
  status chip to 3.43:1 against the page — under the 4.5:1 WCAG 1.4.3 AA floor,
  on the text FRG-UI-047 had just made the only carrier of state.

Recorded under the same delegated authority as the decisions above; no owner
re-approval was sought, and nothing in the change's scope, non-goals or
capability list moves.

## Gate evidence

Tier: medium (UI-only change, no new attack surface). Angles: state
correctness/races, accessibility and keyboard operability, spec/test
traceability, comment hygiene + process conformance, plus an
independent-model full-diff review and a four-angle simplify pass (reuse,
simplification, efficiency, altitude).

Verdict fix-first. Two majors found and closed: the drawer's focus restore
targeted an element still inside the inert subtree — a no-op in every real
browser, invisible to jsdom, and unasserted by the browser tier — fixed by
deferring the restore past the commit that lifts inert; and a monitor
toggle on an entry whose series is unmonitored succeeded at the API then
settled silently back to unmonitored, the exact silent revert FRG-UI-048
forbids — now explained through the alert region, with the single-cause
inference named on both sides of the projection boundary. The e2e tier was
hardened until it could catch both: focus asserted after Escape, the
containment walk fails on focus stranded at the body, the target-floor
sweep opens the drawer before measuring, the scroll guard measures the
real scroller, and the title probe cannot pass vacuously.

Folded minors: aria-busy on the in-flight toggle, the day gutter hidden
from assistive technology (its date now announced exactly once), a focus
ring for the drawer's initial target, undimmed focus indicators on
aria-disabled controls, an axe scan of the open drawer, atomic activation
admission, one refetch per toggle instead of two cancelled ones, offline
mutations failing fast into the revert-and-report path (promoted to
client-wide policy), and comments corrected where claims had drifted from
behavior.

Simplify applied ten cleanups, among them one source for the 24px floor
across all three test tiers, one sr-only utility in the theme layer, one
per-mode class bundle, shared pull-entry fixtures, and a batched e2e
measurement. Follow-ups recorded, deliberately not taken here: a per-entry
component owning its own mutation observer (removes the screen-level
optimistic map and restores per-row re-render isolation); a shared
dismissable-surface hook adopted by Modal — whose Tab-trap containment and
unmount-time focus restore are both weaker than the drawer's — plus a
z-index scale resolving the acknowledged modal-under-drawer stacking; a
focus-ring token with an app-wide sweep; seriesMonitored exposed on the
pull projection so the toggle could be suppressed rather than explained
after the fact; a crossover-resize remount that drops focus and cover
fallback state; a top-level heading for screen titles; and a route-change
announcement for the drawer's primary-navigation path.

Suites at merge: backend 2704 passed / 13 skipped, frontend 586 across 62
files, tsc clean, e2e GREEN 40 pass / 0 fail / 1 skipped including the
a11y tier. comment_check, soup_check, risk_register_check and trace all
exit 0; openspec validate --strict valid. Registry rows stay approved on
the branch by design — the implemented flip lands with the baseline sync,
since an implemented row with no baseline requirement reads as a trace
gap.
