# Design: humble-session-extension

## Context

The Humble store source (m6-humble-source, v0.6.x) authenticates with the operator's
`_simpleauth_sess` session cookie. Humble offers no scoped or read-only API token, so
a live session cookie is the only credential available — a fixed external constraint,
not a foragerr choice (RISK-046). Today the operator obtains that cookie by hand: open
`www.humblebundle.com`, open DevTools → Application → Cookies, copy `_simpleauth_sess`,
paste into the Sources connect card. The session expires in weeks (FRG-SRC-005 models
`expired`), so the ritual recurs. The copy step is the worst UX in the product.

A browser extension already sits inside the origin that holds the cookie and can read
it via the `cookies` API without DevTools. This change builds an extension whose sole
job is to put that cookie on the clipboard on one click, so the operator pastes it into
the **existing, unchanged** connect/reconnect card. The extension does not talk to
foragerr at all — no API key, no endpoint, no network. That keeps the entire
credential-handling surface server-side where it is already built and tested, and
makes the extension a pure convenience over the DevTools copy.

## Goals / Non-Goals

**Goals:**
- One click copies the Humble `_simpleauth_sess` cookie to the clipboard — no DevTools.
- The smallest permission set the task can run on; no network capability at all; no
  standing background activity.
- The extension holds no foragerr credential and makes no request to foragerr.
- One codebase → Chrome + Firefox artifacts, reproducibly built with no new deps.

**Non-Goals:**
- Any extension→foragerr connection; store publication; automated login / stored
  Humble credentials; background copy; a second store. (See proposal Non-goals.)

## Decisions

### 1. Explicit-action, clipboard-only — no network, no content scripts, no storage
The cookie is read **only** in the popup's click handler
(`browser.cookies.get({url: "https://www.humblebundle.com/", name: "_simpleauth_sess"})`)
and written to the clipboard (`navigator.clipboard.writeText` from the popup's user
gesture, `clipboardWrite` permission). There is no content script, no `tabs`, no
`storage`, no `fetch`/`XMLHttpRequest` anywhere in the code, and no background/alarm
activity. The extension is inert except during a deliberate click and can reach only
the Humble cookie and the clipboard. The MV3 service worker holds no state.

### 2. No foragerr coupling — the clipboard is the entire hand-off
The extension does not know foragerr's URL, holds no API key, and requests no host
permission for the foragerr origin. The operator pastes the copied cookie into the
existing `POST /api/v1/sources` / `POST /sources/{id}/reconnect` card, which already
validates live, encrypts at rest, and drops the cookie from responses (FRG-SRC-002,
RISK-045). No backend change, no new endpoint, no CORS/Origin consideration.

### 3. Least-privilege manifest (identical Chrome/Firefox, MV3)
```
permissions:      ["cookies", "clipboardWrite"]
host_permissions: ["https://www.humblebundle.com/*"]
```
No `tabs`, `<all_urls>`, `storage`, `externally_connectable`, `webRequest`, content
scripts, `web_accessible_resources`, `nativeMessaging`, `optional_permissions`,
`optional_host_permissions`, or `content_security_policy` override. `host_permissions`
is a single hard-coded Humble host (needed for the `cookies.get` read); there is no
dynamic/optional host permission because there is no other origin to reach. MV3 forbids
remotely hosted code, so the extension can execute only its shipped, reviewable bundle.

**On the no-egress claim (gate correction).** A narrow `host_permissions` does NOT by
itself prevent write-only exfiltration in MV3 — `fetch(..., {mode:"no-cors"})`,
`sendBeacon`, `Image().src`, `WebSocket`, and `RTCPeerConnection` all reach any origin
with no host permission, and the default MV3 CSP sets no `connect-src`. So the
no-transmission property is not a platform guarantee derived from host scope. It rests
on: the reviewed source containing no egress primitive (the `no-network` test is a
regression tripwire, not a proof — a determined author can obfuscate past any
denylist), MV3's no-remote-code guarantee, and the minimal manifest above (which also
omits `nativeMessaging` and the optional-permission/CSP keys a host permission would
not have blocked) — all verifiable against the reproducible build. The shipped code
contains no egress path; this is the accurate basis for that fact.

### 4. Copy affordance and expiry hint
The popup shows a single "Copy Humble session cookie" button. On success it confirms
"Copied — paste into foragerr's Sources card" without ever displaying the cookie value.
If no `_simpleauth_sess` cookie exists (operator not logged in to Humble), it shows
"log in to Humble first" and copies nothing. Optionally it surfaces the cookie's
expiry timestamp (available from `cookies.get`) as a plain hint so the operator knows
whether a reconnect is even needed — read-only, still no network.

### 5. One codebase, two targets, reproducible build
Plain JS/HTML/CSS, no framework, no npm runtime deps → **no new SOUP entries**. A
`build.mjs` (Node, stdlib only) emits `dist/chrome/` (MV3 `service_worker`) and
`dist/firefox/` (MV3 background scripts + `browser_specific_settings.gecko.id`) from
shared source, then zips each. Firefox is self-distributed as an **unlisted** add-on
signed through AMO (required for install; no store listing); Chrome is loaded unpacked
in developer mode. The build is deterministic (sorted inputs, no timestamps) so the
operator can rebuild and byte-compare against the distributed zip (T-EXT-2 integrity
story). Extension lives in `extension/` at repo root, outside `backend/`/`frontend/`.

## Threat model (STRIDE) — drafted here, lands in docs/security/ at implementation

New/changed elements: **E-EXT** (the extension in the browser profile) and **E-DIST**
(the distributed artifact). Because the extension has no network capability and stores
no foragerr credential, the Spoofing/Elevation-via-key and transit threats of a
connected extension do not exist here.

| ID | STRIDE | Element | Threat | Disposition |
|----|--------|---------|--------|-------------|
| T-EXT-1 | Info disclosure | E-EXT / clipboard | The Humble cookie is briefly on the system clipboard, where a malicious co-installed extension with `clipboardRead` or a clipboard-manager app could read it → access to the operator's Humble account (order history/entitlements). | **Accepted residual (extends RISK-046).** This is the *same* clipboard exposure the manual DevTools copy already has and RISK-046 already accepts — the extension mechanizes the copy, it does not add a new class. It removes the DevTools/OS-copy fumble but not the clipboard hop (the connect card needs a pasteable value). The cookie is Humble-only (no foragerr/OS credential), expires in weeks, and is invalidated by logging out of Humble (surfacing `expired`, FRG-SRC-005). No payment/billing action is reachable with it. Ceiling: any paste-based flow crosses the clipboard. Review trigger: a clipboard-free ingestion path (e.g. native messaging) is ever built, or Humble ships a scoped token. |
| T-EXT-2 | Tampering | E-DIST | Operator installs a tampered build (supply chain of the self-distributed zip) that quietly gains reach or copies elsewhere. | **Mitigated (RISK-050).** Dependency-free, deterministic build the operator runs/verifies themselves; Firefox artifact is AMO-signed; no remote code (MV3); the manifest's `cookies`+`clipboardWrite`+single-host surface is auditable and has no network permission to exfiltrate through. No third-party build pipeline to compromise. |

Permission over-reach is bounded by the minimal, auditable manifest and the reviewed
egress-free source (Decision 3), not by host scope: MV3 does not gate write-only egress
on host permissions, so the real controls are the absence of egress code in a
reproducible bundle, MV3's no-remote-code guarantee, and a manifest that also omits
`nativeMessaging` and the optional-permission/CSP keys. No standing site reach exists
(no content scripts, no `storage`).

Existing rows: **RISK-046 updated** — its mitigation/review text records that the
extension provides a one-click copy replacing the DevTools step, with no foragerr-side
credential introduced (the earlier connected-extension design that would have added an
API-key-at-rest risk was dropped by owner decision). RISK-045 (cookie at rest),
RISK-047 (store-JSON parsing), RISK-048 (signed-URL egress) are untouched — no server
code changes.

## Risks / Trade-offs

- **The clipboard hop remains** (T-EXT-1). The connect card ingests a pasted string, so
  the cookie must reach the clipboard; the extension cannot remove that without a
  different ingestion mechanism (native messaging), which is out of scope and would be
  its own change. Accepted as identical to the status-quo manual copy.
- **Self-distribution over store review** trades an independent security review for
  operator control and no listing overhead — appropriate at one operator; the
  reproducible-build story (RISK-050) is the compensating control.
- **MV3 on Firefox** uses an event-page/background-scripts shape rather than Chrome's
  `service_worker`; the build emits the correct manifest key per target (Decision 5).
  Both run identical popup logic.
- **No backend change** means zero risk to the existing source pipeline — the strongest
  argument for the clipboard-only shape over a connected extension.
