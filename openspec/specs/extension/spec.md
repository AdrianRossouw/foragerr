# EXTENSION — Companion Browser Extension Specification

## Purpose

Baseline requirements for the companion browser extension (Chrome + Firefox,
Manifest V3): a self-distributed helper whose sole job is to copy the operator's
own Humble Bundle session cookie to the clipboard on an explicit click, so it can
be pasted into the existing Sources connect/reconnect card. The extension does not
connect to foragerr — no API key, no network request, no backend endpoint (owner
decision 2026-07-14, clipboard-only). First implemented in the 0.9.x dogfood series
(`humble-session-extension`). Depth here is the implemented change's scenario-level
detail (FRG-PROC-003, FRG-PROC-009); the security analysis lives in
`docs/security/threat-model.md` (T-EXT-1, T-EXT-2) and `docs/security/risk-register.md`
(RISK-046, RISK-050).

## Requirements

### Requirement: FRG-EXT-001 — Explicit-action cookie-to-clipboard copy

The companion browser extension SHALL obtain the operator's Humble
`_simpleauth_sess` session cookie for `www.humblebundle.com` and place it on the
system clipboard ONLY in response to an explicit user action (a click in the
extension popup), reading the cookie via the browser `cookies` API at the moment of
that action. It SHALL NOT display the cookie value to the operator, SHALL NOT inject
any script into humblebundle.com, SHALL NOT read the cookie in any background,
scheduled, or page-load-triggered context, SHALL NOT persist the cookie value, and
SHALL NOT transmit the cookie or any data to any network endpoint.

#### Scenario: Cookie read and copied only on click

- **WHEN** the operator clicks the popup's copy action while logged in to Humble
- **THEN** the extension reads `_simpleauth_sess` and writes it to the clipboard,
  confirming success without showing the value — and performs no other action

#### Scenario: Inert until clicked

- **WHEN** the extension is installed and the operator is logged in to Humble but has
  not clicked the copy action
- **THEN** no cookie is read and nothing is copied — no background, alarm, or
  content-script code path accesses `_simpleauth_sess`

#### Scenario: No live Humble session

- **WHEN** the operator clicks copy but no `_simpleauth_sess` cookie exists (not logged
  in to Humble)
- **THEN** the extension shows a "log in to Humble first" message and copies nothing

#### Scenario: Cookie not retained

- **WHEN** a copy action completes
- **THEN** the extension holds no copy of the cookie value in storage or persistent
  memory — a subsequent copy re-reads it fresh from the browser

### Requirement: FRG-EXT-002 — Least-privilege, no-network permission surface

The extension manifest SHALL request only the `cookies` and `clipboardWrite`
permissions and the single host permission `https://www.humblebundle.com/*`. It SHALL
NOT declare content scripts, `tabs`, `<all_urls>`, `storage`, `webRequest`,
`externally_connectable`, or any host permission other than the Humble host, and SHALL
be Manifest V3 (which forbids remotely hosted code). The extension code SHALL contain
no `fetch`, `XMLHttpRequest`, WebSocket, or other network call — it has no capability
to transmit the cookie anywhere.

#### Scenario: Manifest declares no broad reach and no extra host

- **WHEN** either browser build's `manifest.json` is inspected
- **THEN** `permissions` is exactly `["cookies","clipboardWrite"]`, `host_permissions`
  is exactly the single Humble host, and there is no `content_scripts`, `tabs`,
  `<all_urls>`, `storage`, `externally_connectable`, or `web_accessible_resources`

#### Scenario: No network egress in code

- **WHEN** the extension source is inspected
- **THEN** it contains no `fetch`/`XMLHttpRequest`/WebSocket usage and requests no
  origin beyond the Humble host — the cookie can leave only via the clipboard the
  operator controls

### Requirement: FRG-EXT-003 — Cross-browser parity and reproducible self-distributed build

The extension SHALL be produced from a single source tree into Chrome and Firefox
Manifest V3 artifacts by a build with no third-party runtime or build dependencies
(no new SOUP), and the build SHALL be deterministic so the operator can rebuild and
byte-compare against the distributed artifact. The two builds SHALL run identical popup
copy logic, differing only in the manifest background shape required by each browser.
Distribution SHALL be self-service (Firefox unlisted AMO-signed; Chrome developer-mode
load); no store listing is required.

#### Scenario: Two artifacts, one logic

- **WHEN** the build script runs
- **THEN** it emits a Chrome build (MV3 `service_worker`) and a Firefox build (MV3
  background scripts + `browser_specific_settings.gecko.id`) whose popup/copy sources
  are identical

#### Scenario: Deterministic rebuild

- **WHEN** the build is run twice from the same source
- **THEN** the two output zips are byte-identical (sorted inputs, no embedded
  timestamps), enabling operator verification

#### Scenario: No new dependencies

- **WHEN** the build tooling is inspected
- **THEN** it uses only the language/runtime standard library and adds no entry to
  `docs/security/soup-register.md`
