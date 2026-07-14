# Proposal: humble-session-extension

## Why

Connecting (and re-connecting after expiry) the Humble Bundle source today requires
the operator to open browser DevTools, find the `_simpleauth_sess` cookie, and copy it
before pasting it into the Sources connect card — the single most error-prone, least
explainable step in the product, repeated every few weeks when the session expires
(FRG-SRC-005). The m6-humble-source change explicitly deferred a companion browser
extension as the fix ("coming soon" in the connect card helper text; copy-only auth
model decided 2026-07-11). This change builds it, for Firefox and Chrome, with the
threat analysis done up front so the risk posture is evaluated and recorded before any
code exists.

## What Changes

- **New companion browser extension** (one WebExtension MV3 codebase, Chrome + Firefox
  builds) whose *entire* job is: on an explicit click in its popup, read the
  operator's own `_simpleauth_sess` cookie for `www.humblebundle.com` and place it on
  the system clipboard, so the operator pastes it into the existing Sources connect
  card. It replaces the DevTools "find and copy the cookie" fumble with one click.
- **No connection back to foragerr.** The extension makes no network requests of any
  kind — no foragerr API call, no API key, no host permission for the foragerr origin,
  no new backend endpoint. It touches the cookie and the clipboard, nothing else. The
  existing manual paste into the connect/reconnect card is unchanged and remains the
  ingestion path.
- **Copy-only forever** (standing owner decision): the extension copies an existing
  logged-in session's cookie; it never touches Humble credentials, never automates
  login, never acts on the Humble page (no content scripts).
- **Minimal extension surface**: `cookies` permission plus `clipboardWrite`, and a
  single host permission for `https://www.humblebundle.com/*`. No content scripts, no
  `tabs`, no `<all_urls>`, no `storage`, no `externally_connectable`, no remote code
  (MV3 guarantees), no background activity beyond the click-initiated read-and-copy.
- **No credentials at rest anywhere.** The cookie is read at click time, written to
  the clipboard, and not persisted by the extension; there is no API key or config to
  store.
- **Security artifacts in the same change** (FRG-PROC-006): STRIDE additions
  (T-EXT-1, T-EXT-2) to `docs/security/threat-model.md` and a risk-register entry for
  self-distributed build integrity, plus an update to RISK-046 noting the extension
  mechanizes the same clipboard step (no DevTools) without adding a foragerr-side
  credential — drafted in design.md, committed with the change.
- **Self-distributed builds**: reproducible zips from a dependency-free build script
  (no new SOUP entries); Firefox via AMO unlisted self-distribution signing, Chrome
  via developer-mode load (single-operator deployment). Store publication is out of
  scope.

## Capabilities

### New Capabilities

- `extension` — companion browser extension: explicit-action cookie-to-clipboard copy
  (FRG-EXT-001), least-privilege no-network permission surface (FRG-EXT-002),
  cross-browser parity and reproducible self-distributed builds (FRG-EXT-003).

### Modified Capabilities

None. The backend and the existing Sources connect/reconnect API are unchanged — the
extension feeds the clipboard, and the operator's paste into the existing card is the
only ingestion path.

## Non-goals

- **Any connection from the extension to foragerr** — no API key, no endpoint, no
  network. The clipboard is the only hand-off surface.
- **Store publication** (Chrome Web Store / AMO listed) — self-distribution only.
- **Automated login or stored Humble credentials** — rejected auth model, restated.
- **Background/scheduled cookie copy** — every copy is an explicit user gesture.
- **Any second store source** — Humble only, as shipped.

## Security impact

New attack surface is narrow: (1) the extension's permission to read the Humble cookie
and write the clipboard; (2) the distribution channel (unsigned/self-built artifacts).
There is **no** credential-at-rest, no network egress, and no new server endpoint, so
the m6 concerns (RISK-045 at-rest cookie, RISK-047 store-JSON parsing, RISK-048
signed-URL egress) are untouched. The residual clipboard exposure is the same one
RISK-046 already accepts — the extension replaces the DevTools copy with a one-click
copy, not a new class of risk. STRIDE additions and the build-integrity risk row are
recorded at implementation. No new SOUP (dependency-free build); `tools/soup_check.py`
unaffected.

## Manual impact

`docs/manual/`: Sources chapter gains a "Copy the cookie with the browser extension"
step at the top of the connect/reconnect flow (install, click to copy, paste into the
card); the DevTools cookie-copy instructions are demoted to the fallback path. README
feature list: one line. The connect card's "coming soon" helper text is replaced by a
link to the manual section.

## Registry allocations

FRG-EXT-001..003 (new area `EXT | Companion browser extension` added to the AREA table
in `docs/process/commit-standard.md`), all `proposed`, milestone 0.9.x, in
`docs/traceability/requirements-registry.md`. No `SRC` allocation — no backend change.

## Approval

Approved by Adrian 2026-07-14 (session; "approved implement"). Clipboard-only shape —
no extension→foragerr connection, no API key, no backend change. Implementation
proceeds under FRG-PROC-009.
