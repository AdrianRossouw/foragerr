# calendar-shelf — tasks

## 1. Palette resolution (the bugfix half)

- [x] 1.1 `theme/palettes.ts`: normalized lookup (suffix fold +
      case-insensitive) against the named maps; deterministic derived
      hue (stable hash → HSL bands tuned for the dark shell) for misses;
      never the brand green for a known-name publisher
- [x] 1.2 Tests: live-shape names ("Marvel Comics", "DC Comics", "BOOM!
      Studios", "Dark Horse Comics") resolve to their palette colors;
      unlisted publishers get stable non-accent hues; null stays default

## 2. Shelf rows (FRG-UI-018 / FRG-UI-042)

- [x] 2.1 CalendarScreen row layout at/above the crossover: ~66×99
      cover, title + issue + debut badge, fixed-position publisher chip
      (swatch + normalized name), writer/artist line, two-line
      description clamp, right state/action rail; ≈110px rhythm
- [x] 2.2 Absent enrichment collapses (no placeholders); detail surface
      unchanged; quiet cards below crossover unchanged
- [x] 2.3 Carry the calendar-legibility invariants: 24px targets,
      ~30-char title measure floor, honest state chips, optimistic
      toggle, both modes expose identical actions

## 3. Tests + docs + verification

- [x] 3.1 Vitest: shelf anatomy (chip position independent of title
      length, clamp, creators line, cover size class), palette
      normalization through the UI, adapted legibility tests green
- [x] 3.2 docs/manual/user/web-ui.md calendar section
- [x] 3.3 Full frontend (tsc + vitest) + backend suites green; tools
      exit 0; e2e green incl. adapted browser-tier measures; live-rig
      verification of the shelf on the real week
