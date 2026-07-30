# calendar-legibility — tasks

Nothing here starts before the FRG-PROC-009 approval is recorded in
`proposal.md`, including the interaction decision the proposal leaves open.

## 1. Honest status vs controls (FRG-UI-047)

- [x] 1.1 Replace the Calendar's control-shaped state glyph with a status
      indicator: a chip/dot treatment that reuses no control glyph, is not
      focusable, carries no `button` role or `aria-pressed`, no pointer cursor
      and no control hover state, and exposes its state as text
- [x] 1.2 Restrict the bookmark glyph to entries that carry a real monitor
      toggle; the wanted state on an entry without one no longer renders the
      filled accent bookmark
- [x] 1.3 Shared minimum-target treatment in the token layer (≥ 24 × 24 CSS px)
      applied to the Calendar's controls and the new chrome toggle; real
      controls keep a visible `focus-visible` outline
- [x] 1.4 Tagged vitest (ID in the test name): an unlinked entry in each
      derived state exposes no button and no pressed state; a linked entry's
      toggle is a real `aria-pressed` button; the per-entry button count equals
      the per-entry action count
- [x] 1.5 Browser-driven assertion in the e2e tier: every calendar control and
      the chrome toggle measure ≥ 24 × 24 CSS px on both sides of the crossover
      (axe-core does not cover WCAG 2.5.8) — derived from what is RENDERED, so a
      control inherited from a shared component cannot slip past it, and the axe
      pass itself now runs at both viewports

## 2. Responsive entry presentation (FRG-UI-018)

- [x] 2.1 Record the 900px crossover once in the layout token layer as the
      single value both this screen and the shell's media queries read
- [x] 2.2 Agenda-row mode at or above the crossover: fixed-size thumbnail,
      title as the primary column at body base size wrapping at word
      boundaries, issue · publisher · state meta, right-aligned actions; row
      density such that a ~60-entry day stays near 1.5 viewport heights
- [x] 2.3 Quiet-card mode below the crossover: single column, title spans the
      card width, all actions icon-only on a rail beneath the title block
      (including Add — no labelled button in the title's row), day gutter
      folded into an inline day header
- [x] 2.4 One action set for both modes — no affordance exists in one and not
      the other; covers/spine fallback (FRG-UI-042), debut badge, detail
      expando, not-yet-released marking all preserved in both
- [x] 2.5 Tagged vitest (IDs in names): wide mode renders rows with an
      unclamped, unbroken long title; narrow mode renders cards with an
      icon-only rail; the action set is identical across the crossover
- [x] 2.6 Browser-driven check: a seeded 60-entry day holds every single-line
      entry inside the 36 CSS px per-entry bound (the restated density clause —
      see the proposal's Approval amendment), and the row title keeps its
      ~30-character measure at the crossover width. Measured: 29.0px band,
      1.97 viewport heights for 60 entries; title 200.0px = ~30.9 characters

## 3. Monitor-toggle in-flight feedback (FRG-UI-048)

- [x] 3.1 Optimistic + busy state on the toggle: requested state rendered
      immediately, further activations suppressed until the mutation settles
- [x] 3.2 Settle to the re-projected derived state on success (existing
      invalidations); on failure revert to the true state and surface the
      failure as actionable guidance (FRG-UI-030/033) — never a silent revert
- [x] 3.3 Tagged vitest (ID in the name): immediate requested-state render;
      second activation while in flight issues no second mutation; failure
      reverts and reports; success settles to the projection

## 4. Responsive application chrome (FRG-UI-049)

- [x] 4.1 Sidebar becomes an off-canvas drawer below the crossover: hidden by
      default, labelled header toggle, backdrop, content region spans the
      viewport; at or above the crossover the FRG-UI-023 frame and no toggle
- [x] 4.2 Drawer keyboard behavior: focus into the drawer on open, Escape
      closes and returns focus to the toggle, nav selection navigates and
      closes
- [x] 4.3 Tagged vitest (ID in the name): narrow render exposes the toggle and
      no fixed sidebar column; Escape/backdrop/nav-item all dismiss and
      restore focus; wide render is byte-for-behavior the shipped frame with no
      toggle

## 5. Docs, gate, and verification

- [x] 5.1 `docs/manual/user/web-ui.md`: rewrite the **Calendar** section's
      presentation prose for both widths and for what the monitor affordance is
      and where it exists; correct the **The shell** section's claim that the
      sidebar never moves
- [x] 5.2 Registry rows for FRG-UI-047/048/049 flipped `proposed` →
      `implemented`; traceability regenerated and clean — rows are `approved`
      and the matrix is regenerated; the `implemented` flip lands with the
      baseline spec sync (`tools/trace.py` treats an implemented row with no
      baseline requirement as a gap)
- [x] 5.3 Refresh the README tour shots if the Calendar's appearance changed in
      any embedded screenshot (FRG-PROC-017) — none needed: no README shot shows
      the Calendar, and every shot is a wide-viewport frame, which is unchanged
- [x] 5.4 Merge gate: full frontend + backend suites green, `tools/trace.py`,
      `tools/soup_check.py`, `tools/risk_register_check.py` and
      `tools/comment_check.py` all exit 0, e2e green including the a11y tier,
      medium review fleet + independent-model full-diff review with an
      accessibility angle
