# Tasks: humble-session-extension

## 1. Registry, process, and security groundwork (do first)

- [ ] 1.1 Add `EXT | Companion browser extension` to the AREA table in
  `docs/process/commit-standard.md`.
- [ ] 1.2 Allocate FRG-EXT-001..003 in
  `docs/traceability/requirements-registry.md` (status `proposed`, milestone 0.9.x).
  No `SRC` allocation — no backend change.
- [ ] 1.3 Draft the threat-model additions (T-EXT-1 clipboard residual, T-EXT-2 build
  integrity) as a dated section in `docs/security/threat-model.md`, and update the
  RISK-046 mitigation/review note to record that the extension provides a one-click
  clipboard copy replacing the DevTools step, introducing no foragerr-side credential.
- [ ] 1.4 Add risk-register row RISK-050 (self-distributed build integrity) to
  `docs/security/risk-register.md` with category, likelihood/impact, disposition, and
  review trigger per design.md; confirm T-EXT-1 is folded into the updated RISK-046
  row rather than duplicated.
- [ ] 1.5 Record owner approval in proposal.md `## Approval` before implementation
  (FRG-PROC-009 gate).

## 2. Extension: shared source (FRG-EXT-001, FRG-EXT-002)

- [ ] 2.1 Create `extension/` at repo root: `src/popup.html`, `src/popup.js`,
  `src/background.js` (no-state MV3 worker), shared `manifest.base.json`. Plain
  JS/HTML/CSS, no framework, no `storage`.
- [ ] 2.2 Implement click-time cookie read
  (`cookies.get({url, name:"_simpleauth_sess"})`) and clipboard write
  (`navigator.clipboard.writeText` from the popup gesture); never display the cookie;
  hold no copy after the write (FRG-EXT-001).
- [ ] 2.3 "Log in to Humble first" handling when no `_simpleauth_sess` cookie exists;
  optional read-only expiry-timestamp hint in the popup.
- [ ] 2.4 Manifest: exactly `["cookies","clipboardWrite"]` + the single Humble host;
  no content scripts, `tabs`, `<all_urls>`, `storage`, `externally_connectable`; no
  `fetch`/XHR/WebSocket anywhere in the code (FRG-EXT-002).

## 3. Extension: build, parity, distribution (FRG-EXT-003)

- [ ] 3.1 `extension/build.mjs` (Node stdlib only): emit `dist/chrome/` (MV3
  `service_worker`) and `dist/firefox/` (MV3 background scripts +
  `browser_specific_settings.gecko.id`) from shared source; deterministic zips
  (sorted inputs, no timestamps).
- [ ] 3.2 Verify no new SOUP entry is required (`tools/soup_check.py` stays green);
  document the dependency-free build in `extension/README.md`.
- [ ] 3.3 Firefox unlisted AMO-signing steps and Chrome developer-mode load documented
  in `extension/README.md`; note the byte-compare verification path.

## 4. Extension tests (FRG-EXT-001..003)

- [ ] 4.1 Unit tests (vitest, IDs in test names) over the pure copy logic with a mocked
  `browser` API: cookie read only on the click path; clipboard written with the cookie
  value; cookie not retained post-copy; no-Humble-session branch copies nothing.
- [ ] 4.2 Manifest assertion test: both built manifests declare exactly
  `["cookies","clipboardWrite"]` + the single Humble host, no content scripts / broad
  permissions / extra host (FRG-EXT-002).
- [ ] 4.3 Source-scan test: no `fetch`/`XMLHttpRequest`/WebSocket in the extension
  source (no-network invariant, FRG-EXT-002).
- [ ] 4.4 Deterministic-build test: two runs produce byte-identical zips (FRG-EXT-003).

## 5. Docs

- [ ] 5.1 `docs/manual/`: Sources chapter — add "Copy the cookie with the browser
  extension" as the top step of the connect/reconnect flow (install, click to copy,
  paste into the card); demote the DevTools cookie-copy steps to a labeled fallback.
- [ ] 5.2 Replace the Sources connect-card "extension coming soon" helper text with a
  link to the new manual section (frontend).
- [ ] 5.3 README: one feature line for the companion extension.
- [ ] 5.4 Regenerate the traceability matrix; flip FRG-EXT-001..003 to `implemented`;
  run `soup_check.py`, `risk_register_check.py`, `trace.py` at the merge gate (all
  exit 0).
