# foragerr — Humble cookie helper (browser extension)

A tiny companion browser extension (Chrome + Firefox, Manifest V3) whose entire
job is to copy your logged-in Humble Bundle session cookie (`_simpleauth_sess`)
to the clipboard on one click, so you can paste it into foragerr's **Sources**
connect/reconnect card. It replaces the manual "open DevTools, find the cookie,
copy it" step.

**It does not connect to foragerr.** No API key, no network requests, no
background activity. It reads the cookie only when you click, writes it to the
clipboard, and does nothing else. See the requirements FRG-EXT-001..003 and the
threat analysis (T-EXT-1/T-EXT-2, RISK-046/RISK-050) in `docs/security/`.

## Permissions (and why)

| Permission | Why |
|------------|-----|
| `cookies` | read `_simpleauth_sess` for `www.humblebundle.com` |
| `clipboardWrite` | put the cookie on the clipboard for you to paste |
| host: `https://www.humblebundle.com/*` | the cookie domain the read is scoped to |

No `tabs`, no `storage`, no content scripts, no extra host, and no
`fetch`/`XMLHttpRequest`/WebSocket anywhere in the source — the cookie can leave
only via the clipboard you control.

## Build

Requires only Node (standard library — no dependencies to install):

```bash
node build.mjs        # or: npm run build
```

This emits:

- `dist/chrome/` + `dist/chrome.zip` — MV3 `service_worker`
- `dist/firefox/` + `dist/firefox.zip` — MV3 background scripts + a Gecko add-on id

The build is **deterministic**: STORED zips with fixed 1980 timestamps and
sorted entries, so two runs from the same source produce byte-identical zips.
Verify a distributed artifact against your own rebuild:

```bash
node build.mjs
sha256sum dist/chrome.zip dist/firefox.zip
```

## Test

```bash
node --test        # or: npm test
```

Covers the copy logic (cookie read on click, clipboard write, no retention, the
no-session branch), the manifest surface (exact permissions, no broad reach),
the no-network source invariant, and build reproducibility.

## Install

**Chrome** (developer mode, single-operator):

1. `chrome://extensions` → enable **Developer mode**.
2. **Load unpacked** → select `dist/chrome/`.

**Firefox** (self-distributed, unlisted):

1. Sign the `dist/firefox.zip` as an **unlisted** add-on via
   [AMO](https://addons.mozilla.org/developers/) (`web-ext sign` or the
   Developer Hub). Unlisted signing is required for permanent install; there is
   no public store listing.
2. Install the signed `.xpi` from `about:addons` → gear → **Install Add-on From
   File**.

## Use

1. Sign in at humblebundle.com.
2. Click the extension → **Copy Humble session cookie**.
3. Paste into foragerr → **Sources** → the connect (or reconnect) card.

If it says "no Humble session found", log in to Humble first. The popup shows a
rough validity hint from the cookie's expiry so you know when a reconnect is due.
