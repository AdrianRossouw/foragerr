# ant-mark — tasks

## 1. The swap

- [x] 1.1 LogoMarkIcon: transplant the appmarkant vector paths (bubble outline + ant, currentColor, size-prop contract preserved)
- [x] 1.2 Lockup treatment: retire the gradient tile in AppShell.module.css / LoginScreen.module.css; mark renders accent-on-chrome; comments updated
- [x] 1.3 Tokens: remove --color-logo-tile-from/to, --color-logo-mark, --shadow-logo-tile (+ their hexes from tokens.test.ts palette list); keep --color-logo-word
- [x] 1.4 favicon.svg: faviconant variant (filled accent bubble, dark ant knockout)
- [x] 1.5 Frontend suite + tsc green (FRG-UI-002/023 tagged tests pass against new values)

## 2. Downstream

- [ ] 2.1 Design-system re-sync (LogoMarkIcon + chrome components re-verify; anchored driver upload)
- [ ] 2.2 Post-merge: README screenshot refresh (FRG-PROC-017)
