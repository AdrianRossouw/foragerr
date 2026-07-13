# ant-mark

## Why

The owner selected a new brand mark from the Claude Design logo exploration (project "Foragerr logo design iterations", 2026-07-13): the forager ant inside a comic speech bubble — replacing the gradient-tile hexagon-ant lockup adopted from the 2026-07-10 designer handoff. The ant-in-balloon mark reads the brand story (an ant that forages comics) in one shape and holds up from favicon to hero size.

## What Changes

- `LogoMarkIcon` (the single SVG source for the in-app mark: sidebar lockup, login card) redraws to the speech-bubble ant, staying `currentColor`-drawn with the same `size` prop contract — no call-site changes.
- The sidebar/login lockup drops the gradient tile treatment: the mark renders as an accent-green line drawing directly on the chrome, so the `--color-logo-tile-from/to`, `--color-logo-mark`, and `--shadow-logo-tile` tokens retire (`--color-logo-word` stays for the wordmark). Wordmark text/typography unchanged.
- `favicon.svg` redraws to the filled-bubble variant (accent bubble, dark ant knockout) — legible at 16px on light and dark tabs.
- The design-system project re-syncs after the change lands so Claude Design builds with the new mark.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

(none — brand asset/token *values* change; FRG-UI-002's token-driven-branding and FRG-UI-023's lockup requirements are unchanged and their tagged tests continue to pass against the new values. `openspec validate` flags open delta-less changes; the archived m4-shell-hotfix precedent establishes the shape, and the flag clears at archive.)

## Impact

- **Code**: `frontend/src/components/icons.tsx` (LogoMarkIcon paths), `frontend/src/components/AppShell.module.css` + `frontend/src/screens/auth/LoginScreen.module.css` (lockup treatment), `frontend/src/theme/tokens.css` + `tokens.test.ts` palette list (retired tokens), `frontend/public/favicon.svg`.
- **Docs**: README gains a centered logo masthead (docs/assets/foragerr-mark.svg) and a tightened intro, so the project reads as a real project (FRG-PROC-014 labelling). README screenshot refresh (FRG-PROC-017) queued as a post-merge step — screenshots show the old mark until regenerated.
- **Dependencies / SOUP / security / registry**: none.
- **Design provenance**: vector paths transplanted from the owner's design project (variants `appmarkant` / `faviconant`), not redrawn.

## Approval

Approved — Adrian, 2026-07-13 (in-session: "Full adoption" selected from the presented options).
