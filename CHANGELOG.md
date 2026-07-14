# Changelog

All notable changes to foragerr are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and this project follows
Semantic Versioning per **FRG-PROC-013** (`openspec/specs/dev-process/spec.md`).

These entries record the tagged milestones on `main` for traceability and
history. Each release is also published as a GitHub Release carrying the same
notes. There is no published container image and no support expectation — see
README `License & contributions`.

## [v0.9.7] — 2026-07-14

Refreshed README screenshots and repaired the screenshot-refresh tooling that
broke when mandatory authentication landed.

### Fixed
- **README screenshot refresh** (FRG-PROC-017): `tools/refresh-readme-shots.sh`
  had been broken since mandatory login (M8, v0.7.0) — the backend fail-fasts
  without an operator account and every API call sits behind the default-deny
  perimeter, but the tool seeded no credentials, so the shots had not been
  regenerable. It now boots a throwaway admin, authenticates (cookie-jar login
  with a same-origin `Origin` header for the CSRF check), routes the populate
  calls through an authenticated helper, and the Playwright capture logs in
  before shooting.

### Changed
- The screenshot demo library is now a dedicated public-domain-only path
  (`COMICS_DIR` default `/comics/_pd-demo`), segregated from any working/testing
  root so copyrighted or half-imported content cannot poison public README
  screenshots or abort the run on the completeness guard.
- Regenerated all seven README screenshots against the current UI: they now show
  the v0.9.5 ant brand mark, the authenticated app chrome, and the shipped
  Humble cookie extension helper text.

## [v0.9.6] — 2026-07-14

humble-session-extension: a companion browser extension that copies the Humble
session cookie to the clipboard, replacing the DevTools copy step.

### Added
- **Companion browser extension** (FRG-EXT-001, FRG-EXT-002, FRG-EXT-003): a
  Chrome + Firefox Manifest V3 extension (in `extension/`) whose sole job is to
  copy the operator's Humble `_simpleauth_sess` cookie to the clipboard on one
  popup click, to paste into the existing **Sources** connect/reconnect card. It
  is **clipboard-only**: it never connects to foragerr, holds no API key, and
  makes no network request — the backend and the connect API are unchanged. New
  `EXT` requirement area. Least-privilege manifest (`cookies` + `clipboardWrite`
  + the single Humble host, no content scripts, no network); dependency-free
  deterministic build the operator can byte-verify; self-distributed (Firefox
  unlisted AMO signing, Chrome developer-mode load).

### Changed
- The Sources connect-card helper now points to the shipped extension (the
  "coming soon" chip is gone); the manual leads with the one-click copy and
  keeps the DevTools cookie-copy as a documented fallback.

### Security
- Full STRIDE/risk analysis landed before the code (FRG-PROC-006): T-EXT-1
  (clipboard residual, folded into RISK-046 — the extension mechanizes the
  existing copy, adding no new exposure class) and T-EXT-2 / RISK-050
  (self-distributed build integrity). An adversarial review plus an independent
  Codex pass confirmed the no-egress / no-retention guarantees hold in the
  shipped code; their findings (a build-race test flake, an overstated
  "host-permission ⇒ no egress" claim, and test-rigor gaps) were applied before
  merge.

## [v0.9.5] — 2026-07-13

ant-mark: brand refresh — the forager ant in a speech bubble.

### Changed
- **New brand mark** (FRG-UI-002, FRG-UI-023): the logo becomes the owner's
  finished vector — a forager ant carrying a comic in a speech bubble — as the
  in-app `LogoMarkIcon` (sidebar + login lockups), with a simplified variant as
  the 16px browser-tab favicon where the detailed mark would be illegible. The
  lockup drops its gradient tile (the mark renders in the brand accent on the
  chrome); the retired tile tokens are removed. The README gains a centered
  logo masthead and a tightened intro.

## [v0.9.4] — 2026-07-13

logout-failure-handling: a security bugfix from dogfooding — the logout
control no longer reports success when the server did not confirm it.

### Fixed
- **Logout signals success only on server-confirmed termination**
  (FRG-AUTH-004). The control previously cleared client auth state and
  returned to the login screen on every attempt, even when the logout request
  failed — presenting a signed-out UI while the HttpOnly session cookie stayed
  live, so a reload silently re-authenticated (a shared-device exposure). Now
  a confirmed logout clears and returns to login; a failed one keeps you
  signed in and shows a retryable "try again" message. No server change — the
  endpoint already terminated the session and 204s; this closes the
  client-side false-success.

## [v0.9.3] — 2026-07-13

cbr-support: the second 0.9.x dogfood-series change — CBR comics become
readable on the iPad, closing the biggest daily-usability gap (69% of the
owner's real library was CBR, unreadable in Panels).

### Added
- **CBR (RAR) page streaming over OPDS** (FRG-OPDS-016): the archive layer
  gains a RAR backend (`rarfile` + `unrar-free`, both OSI-licensed, shipped in
  the Docker image) behind a single magic-byte-dispatched opener seam, with the
  same resource-limit and path-confinement posture as ZIP. Every `.cbr` now
  page-streams like a `.cbz`; a CBR imported before this support heals lazily
  (its page count is computed on first open — no re-import). A zip renamed
  `.cbr` (and the reverse) opens by content. Encrypted/damaged archives degrade
  to download-only, never an error.
- **Opt-in CBR→CBZ conversion** (FRG-PP-018, off by default): `convert_cbr_to_cbz`
  converts at import under verify-before-discard (the produced CBZ is verified
  before the original is removed, and the swap is crash-safe — the original is
  deleted only after the DB commit is durable). On-demand per-series/per-issue
  conversion via `POST /api/v1/convert/...`.

### Security
- The RAR parser is new attack surface over untrusted input (T-OPDS-7,
  RISK-049): STRIDE analysis + risk register updated; the convert path re-gates
  on the same `inspect_archive`/`safe_to_extract` vetting as streaming, on both
  import-time and on-demand routes. Adversarially reviewed (metadata-lie
  decompression bomb, path traversal, symlink, encrypted, forged magic — all
  contained) and corpus-validated (473/473 of the owner's real CBRs stream via
  `unrar-free`; libarchive refuted as a fallback).

### Notes
- PDFs remain download-only (readers open a downloaded PDF fine); PDF→CBZ is
  deferred to a later format-preferences change.

## [v0.9.2] — 2026-07-13

naming-defaults: the first 0.9.x dogfood-series change — library adoption
becomes non-destructive by default, and filename identity tags become durable.

### Changed
- **Renaming is off by default** (FRG-PP-020, **BREAKING for fresh installs
  only**): a new install adopts an existing library byte-for-byte and
  name-for-name; downloads keep their release names unless renaming is
  enabled. Existing installs keep their persisted configuration unchanged.
- **Default naming template drops the internal-id tag** (FRG-PP-009): now
  `{Series Title} {Issue Number:000} ({Year})`. The round-trip validation
  (rendered names must re-parse to the same issue) is unchanged.

### Added
- **`{CvIssueId}` naming token** (FRG-PP-009): renders the ComicVine issue id
  as `[cvid-<ID>]` — the durable identity tag that survives database resets
  and reinstalls; recognized by the parser into the existing ComicVine-id
  evidence path. `{IssueId}` remains supported for already-stamped libraries.

### Fixed
- **Stale identity tags can no longer override a disagreeing filename**
  (FRG-PP-003): a `[__id__]` tag whose issue contradicts the parsed filename
  (different series, or a contradicted issue number) now falls through to the
  filename heuristics on every import path — closing the reinstall hazard
  where old tags point at arbitrary rows in a new database. Tag-only
  unparseable names (the DDL convention) still resolve by tag.

### Upgrade notes
- Existing installs: no action; persisted config wins. To adopt the new
  defaults, set `rename_enabled: false` / clear the template override.
- Libraries stamped under the old default keep their `[__id__]` filenames;
  they are harmless under the new guard, and a rename pass with the new
  template (plus `{CvIssueId}` if you want durable tags) cleans them up.

## [v0.9.1] — 2026-07-12

m8-rate-audit-followups: fixes and hardening from a full eight-angle + Codex
backstop review of the v0.9.0 release. No requirement changes.

### Fixed
- **Login form now handles throttling** (FRG-AUTH-009): a 429 from the
  failed-attempt throttle previously fell into the generic "Could not sign in.
  Try again." message — which contradicted the documented backoff (a throttled
  operator should *wait*, not retry). The form now shows "Too many failed
  attempts. Please wait a moment before trying again."

### Changed
- **`audit_event` can never break the request it audits** (FRG-AUTH-009): the
  never-raise property is now enforced by a swallow-all guard rather than
  holding only by construction, so a future caller cannot take down the auth
  path through a raising field value.
- **Rate-limiter memory tightened** (FRG-AUTH-009): the global observation
  counter is bounded by a size cap (O(threshold)) rather than the time window,
  and emptied per-key windows are reclaimed immediately. Internal dedup of the
  shared `client_ip` and throttle-refusal helpers; no behavior change.

## [v0.9.0] — 2026-07-12

m8-rate-audit: failed-auth rate limiting and structured audit events — the
third and last M8 authentication change. M8 is complete.

### Added
- **Failed-attempt throttling** (FRG-AUTH-009): 5 failed attempts within 15
  minutes from one address, on one surface (login form, `X-Api-Key`, OPDS
  Basic), and further attempts on that (address, surface) pair get `429 Too
  Many Requests` with a `Retry-After` deadline that starts at 30 s and doubles
  per additional failure, capped at the window length. **Never a lockout**:
  once the deadline passes, correct credentials succeed normally, and a
  success resets the counter immediately — env re-seed remains the only
  recovery path, unrelated to this throttle. OPDS readers get the `429`
  instead of a repeating `401`/Basic-challenge re-prompt loop. Counters are
  in-process and reset on restart.
- **Unified structured audit events** (FRG-AUTH-009): every authentication-
  relevant event — login success/failure, logout, OPDS verification,
  API-key failure, throttling, and every credential-lifecycle action — is now
  a structured `auth.*` event on the standard logging pipeline, visible in
  **System → Logs** (filter by the `foragerr.auth` logger) and the rotated
  log file. The ad-hoc lines from `m8-auth-core`/`m8-keys-opds` migrate into
  the same shape. No event ever carries credential material; the submitted
  username (the one attacker-controlled field) is control-character-stripped
  and length-capped before it's logged.
- **Leaked-key visibility** (`auth.apikey_source_seen`): rather than logging
  every API-key request, foragerr logs the first successful use of the key
  from a given source address within the window, then stays quiet about
  repeats — so a leaked key surfaces in the audit trail the moment it's used
  from a new address. Key rotation resets the baseline.

### Security
- FRG-AUTH-009 flips to implemented; RISK-020's rate-limit/audit residual
  closes. The limiter check runs before any scrypt verification on all three
  credential-bearing surfaces, shielding the deliberately constant-work KDF
  from failure-flood CPU exhaustion. A per-surface global counter observes
  distributed failure patterns (`auth.backoff_triggered`) without ever
  blocking, by design — it must never become a vector for locking the
  operator out via spoofed-source spraying. Threat-model notes added for the
  brute-force mitigation (backoff, not lockout), the client-IP trust boundary
  (`X-Forwarded-For` is not trusted — no reverse proxy in the deployment
  model), and log-injection hardening.

### Notes
- No migration, no configuration change (thresholds are module constants).
  No dependency changes — stdlib only (`tools/soup_check.py` unaffected).

## [v0.8.0] — 2026-07-12

m8-keys-opds: credential lifecycle — the second M8 authentication change.
Everything seeded at bootstrap is now manageable from **Settings → Security**.

### Added
- **Settings → Security** (FRG-AUTH-004/005/007): change the web password
  (every *other* session is signed out; the one you're using stays), change
  the OPDS password independently (readers re-prompt; web/API untouched),
  rotate the API key (old key dies immediately; the new one is shown exactly
  once, with copy), and **Sign out everywhere** (deletes every session,
  including the current one — the shared-device recovery). Every credential
  change re-asks for the current admin password; a browser session alone
  can't mint a key or change a password.
- **OPDS Basic verify-cache** (FRG-AUTH-005): reader apps send credentials on
  every request — a positive-only 60 s in-process cache now skips the repeated
  scrypt verification. Failures are never cached, and any credential change
  clears it immediately.

### Changed
- **Environment re-seed semantics** (FRG-AUTH-002): on boot, foragerr now
  compares `FORAGERR_ADMIN_USER`/`FORAGERR_ADMIN_PASSWORD` (and
  `FORAGERR_OPDS_PASSWORD`, independently) against the value the environment
  *last seeded*, not against the live credential. A stale env password left in
  compose no longer silently reverts an in-app password change on every boot.
  Consequence: lockout recovery requires a **new** env value — re-asserting a
  previously seeded one is a no-op. No configuration change is required for
  this release; migration 0024 adds the fingerprint columns.

### Security
- FRG-AUTH-005/006/007 flip to implemented; RISK-003's credential-independence
  residual closes. Threat-model notes added for the re-auth rule, re-seed
  fingerprints (scrypt, same protection class as the live hashes), the
  verify-cache exposure bound, and display-once key confinement (verified by
  test: the rotated key is absent from DOM, query cache, and localStorage
  after the dialog closes).

## [v0.7.0] — 2026-07-12

m8-auth-core: the first change of the M8 authentication milestone. Login is
now mandatory on every surface — the milestone the 1.0 roadmap names as the
gate for "safe for strangers to deploy".

### ⚠ BREAKING — upgrade steps required

This release refuses to start until two new environment variables are set:

```yaml
environment:
  - FORAGERR_ADMIN_USER=you
  - FORAGERR_ADMIN_PASSWORD=choose-a-strong-one
```

They seed the single account at first boot. Setting a *new* pair later and
restarting re-seeds the account (this is the lost-password recovery) and signs
out all sessions. Optionally set `FORAGERR_OPDS_PASSWORD` to give OPDS reader
apps their own password (defaults to the admin password). Rolling back below
v0.7.0 re-opens the unauthenticated surface (the pre-M8 posture).

### Added
- **Mandatory authentication with a default-deny perimeter** (FRG-AUTH-002,
  FRG-AUTH-010): every surface — web UI, REST API, OPDS, WebSocket — now
  requires its credential; the exempt list is exactly `/health` and the login
  screen. There is no auth-mode-none. The uniform-coverage invariant is proven
  three ways: perimeter-by-construction at the app root, an exhaustive
  route-inventory test, and end-to-end negative paths on every surface.
- **Form login with two-tier sessions** (FRG-AUTH-004): "Remember this
  device" keeps a sliding ~90-day session; otherwise sessions slide at ~24 h
  of inactivity (both configurable). Sessions are server-side revocable:
  logout works from the header, and a password change signs out every other
  device. Session tokens are stored hashed; cookies are HttpOnly/SameSite=Lax.
- **scrypt password hashing** (FRG-AUTH-003, amended from "argon2id or
  bcrypt" by owner decision): memory-hard KDF from the existing
  `cryptography` dependency — no new dependencies.
- **Per-surface credentials**: session cookie for the UI, `X-Api-Key` header
  (never a query parameter) for programmatic API use — the generated key is
  shown once to a logged-in session via `/api/v1/auth/bootstrap-key` — and
  HTTP Basic in a dedicated realm for OPDS readers (key rotation and OPDS
  password change UI arrive in the next M8 change).
- **CSRF and WebSocket-origin protection** (FRG-SEC-005): state-changing
  requests under cookie auth require a matching Origin; cross-origin
  WebSocket handshakes are refused before upgrade (allowlist configurable for
  reverse-proxy deployments).

### Changed
- The interactive API docs (Swagger/redoc) are removed and `openapi.json` now
  requires authentication — unauthenticated schema disclosure ends with the
  no-auth posture.
- RISK-020 (the M1 no-auth accepted risk) flips to **Mitigated**; FRG-AUTH-001
  is withdrawn and its scenarios invert into the perimeter tests.

## [v0.6.3] — 2026-07-12

v0-6-3-fixes: the first live SABnzbd run (real indexer, real usenet servers)
found and fixed the bug that broke every real usenet grab since v0.1.0.

### Fixed
- **Real NZBs validate again** (FRG-DL-003, FRG-SEC-002): the NZB 1.1 spec
  mandates a `<!DOCTYPE nzb PUBLIC "-//newzBin//DTD NZB 1.1//EN">` header, but
  grab validation parsed NZBs with the blanket hardened parser whose DOCTYPE
  ban rejected them all — so no spec-conformant NZB from a real indexer ever
  reached SABnzbd (test fixtures omitted the DOCTYPE and hid it). NZB bytes now
  parse via a dedicated entry point that tolerates the mandated DOCTYPE as
  inert while still rejecting entity declarations (billion-laughs), external
  entity resolution (XXE), and oversized bodies; every other XML surface keeps
  full DOCTYPE rejection. Verified live: a real DogNZB release grabbed through
  the API, downloaded by SABnzbd from a real news server, and imported.
  Fixtures are now spec-shaped so the whole suite exercises the real format.
- **Stable traceability-matrix regeneration** (FRG-PROC-005): per-requirement
  test lists are emitted sorted, so regenerating the matrix no longer
  reshuffles cells run-to-run.

### Changed
- **README Sources screenshot** now shows a real connected Humble Bundle
  account with its review queue (owner-supplied session; captured from the
  owner's own purchases). The screenshot tool falls back to the connect-card
  capture on unconfigured instances.

## [v0.6.2] — 2026-07-12

m6-humble-source: Humble Bundle store source — connect the account you already
own comics on and bring your DRM-free purchases into the library through a
review-first sync (FRG-SRC-001..007, FRG-UI-029).

### Added
- **Humble Bundle as a store source** (FRG-SRC-001, FRG-SRC-002): a new
  top-level **Sources** screen connects Humble Bundle by pasting your
  `_simpleauth_sess` session cookie. The cookie is validated with a live
  order-list call before anything is saved, then stored server-side encrypted at
  rest under the keystore (FRG-AUTH-008) and never returned in any API response
  or log. foragerr never stores your Humble password and never automates login.
  The store model is generic so further storefronts can be added without
  reshaping it.
- **Entitlement sync, daily and on demand** (FRG-SRC-003): foragerr polls your
  Humble orders on a schedule (default daily) and whenever you press **Sync
  now**, diffing by store-native key so re-syncs never duplicate. Items are
  classified comic or other; non-comic purchases (games, prose books) are kept
  and shown on demand rather than silently dropped, and malformed order entries
  are skipped and logged without failing the sync.
- **Review-first workflow, auto-sync off by default** (FRG-SRC-004): every newly
  discovered comic lands in a review state with a server-proposed library match.
  Nothing downloads until you accept it — match to an existing series, add as
  new, ignore, or restore, one at a time or in bulk (with shift-range select). A
  per-source **auto-sync** toggle can accept-and-download confidently matched new
  items automatically, and it defaults to **off**. Ignoring an accepted item
  cancels its download wherever it is — a queued or in-flight grab aborts at its
  re-read guard, a completed download awaiting import is withdrawn from the
  import queue, and an import already claimed by the drain is re-checked inside
  the import transaction and imports nothing. A later restore + re-accept always
  downloads afresh.
- **Collected-edition reconciliation that never suppresses singles**
  (FRG-SRC-007): accepting a collected edition marks exactly the issues it fills
  as owned-via-edition, leaves any issue you already own as a single untouched
  (no replacement, no double-counting), and adds OGNs/artbooks with no
  single-issue mapping as standalone items. The FRG-SER-019 invariant is extended
  to sources — reconciliation only ever moves an issue to owned, never clears a
  wanted flag.
- **Verified downloads into the standard import pipeline** (FRG-SRC-006):
  accepting an entitlement fetches a fresh signed URL at grab time, streams it
  over HTTPS with bounded size and timeout, confines egress to the Humble CDN
  host allowlist, verifies the file against the API-provided md5, and hands the
  verified file to the existing import pipeline as a normal completed download.
  Checksum mismatches are quarantined and off-allowlist or non-HTTPS URLs are
  refused, each surfaced on the entitlement with a reason and a retry.
- **Session expiry as a first-class state** (FRG-SRC-005, FRG-UI-029): an auth
  failure during sync flips the source to **expired** and pauses further calls
  against the dead session instead of retrying blindly. The condition surfaces
  through component health, a global reconnect banner, an amber header/footer
  treatment, and a `!` on the Sources nav badge; pasting a fresh cookie
  revalidates, clears all three, and resumes sync. Expiry and disconnect never
  remove or degrade already-synced or imported data.

## [v0.6.1] — 2026-07-12

m6-keystore: at-rest encryption of stored provider secrets (FRG-AUTH-008).

> **⚠️ BREAKING — set `FORAGERR_SECRET_KEY` before upgrading.** foragerr now
> **requires** the `FORAGERR_SECRET_KEY` environment variable (an operator-chosen
> passphrase) and refuses to start without it, naming the variable in the error.
> Generate a strong value once — `FORAGERR_SECRET_KEY="$(openssl rand -base64 32)"`
> — add it to your container's environment, and keep it stable across restarts. On
> first boot after upgrade, foragerr transparently encrypts any existing plaintext
> provider secrets in the database under this passphrase. A changed or lost
> passphrase costs **re-entry of your provider secrets, never data** (see
> `docs/manual/admin/secrets.md`).

### Added
- **At-rest secret encryption** (FRG-AUTH-008): UI-entered provider secrets
  (indexer API keys, SABnzbd credentials) are now stored encrypted in the
  database as `enc:v1:<token>` using authenticated encryption (Fernet:
  AES-128-CBC + HMAC-SHA256, via MultiFernet for a future key-rotation hook).
  The encryption key is derived from the `FORAGERR_SECRET_KEY` passphrase with
  scrypt and a random per-deployment salt; only the non-secret salt and a
  sentinel check-value are persisted (new `keystore_meta` table). A copy of the
  database — including any backup — no longer exposes provider secrets without
  the environment passphrase. New secret fields are covered automatically (the
  `SecretStr` annotation is the single source of truth), and `cryptography` is
  added as a SOUP dependency.
- **Mandatory startup key** (FRG-AUTH-011): the `FORAGERR_SECRET_KEY` passphrase
  is required at startup; a keyless boot fails config validation before touching
  the database, with an actionable error.

### Changed
- **Decrypt-fail-soft** (FRG-AUTH-012): if a stored secret cannot be decrypted
  (passphrase changed, or a backup restored into a different deployment), foragerr
  still starts and serves normally — library browsing and OPDS are unaffected —
  and the affected integration reports "credential unavailable — encryption key
  missing or changed; re-enter the secret" on the health screen, behaving as
  unconfigured. Re-entering the secret re-encrypts it under the current key and
  clears the warning.
- **Plaintext migration on first keyed boot** (FRG-AUTH-013): existing plaintext
  provider secrets are converted to `enc:v1:` ciphertext exactly once,
  idempotently, also covering a restored pre-upgrade (plaintext) backup.
- RISK-041 (plaintext credentials in backups) moves **Accept → Mitigated**;
  residual weak-passphrase risk noted. Threat model updated.

## [v0.6.0] — 2026-07-12

cv-budget-caching: ComicVine politeness grows an hourly dimension — M6 opens.

### Added
- **Per-path hourly ComicVine budget** (FRG-META-016): foragerr now
  accounts its ComicVine requests per resource path over a rolling hour
  (soft ceiling 150/path/hour, configurable via
  `comicvine_hourly_path_budget`, never above ComicVine's documented 200)
  and defers work locally instead of running into ComicVine's server-side
  block. Deferrals are visible in health (per-path usage once a path
  passes 80%, plus an exhausted flag with time-to-resume) and resume by
  themselves: credit backfill continues on later refreshes, background
  fetches retry via their normal staleness paths, and interactive
  searches show an honest "retries in about N minutes" message.
- **Unchanged-series refresh short-circuit** (FRG-META-017): a series
  refresh now skips the full issue walk when ComicVine reports the volume
  unchanged since the last complete walk (and that walk is under
  `comicvine_refresh_max_skip_days` old, default 7) — refreshing a stable
  library costs about one request per series instead of a full page walk
  each. Credit backfill, cover maintenance, and change notifications
  still run; the periodic full walk remains the correctness backstop.

### Fixed
- **Covers appear without a reload** (FRG-META-013): the cover-cache
  write now announces itself on the event stream, so an open series page
  repaints the cover when it arrives instead of waiting for a manual
  refresh.

## [v0.5.5] — 2026-07-11

m5-creator-suggestions: "More from" a creator — M5 complete.

### Added
- **More from <creator>** (FRG-CRTR-005, FRG-API-024, FRG-UI-028): a
  creator's profile now shows their wider ComicVine bibliography that
  isn't in your library — gathered on first view by a bounded background
  fetch (newest 24 volumes, refreshed weekly, served from a local cache
  so profile loads never wait on ComicVine), each entry carrying an
  **Add to library** button into the normal add flow. foragerr never adds
  a series by itself.

This closes M5 (creators & follows): credits, the Creators screens,
explicit-only follows, live ingest, and discovery suggestions.

## [v0.5.4] — 2026-07-11

calendar-discovery-default: the Calendar opens on the whole week.

### Changed
- **Calendar defaults to All releases** (FRG-UI-018, owner decision): the
  weekly view doubles as discovery of books you don't follow yet — the
  Mylar pull-list philosophy — so it now opens on the full week, with the
  Following scope one click away to narrow to your library.

## [v0.5.3] — 2026-07-11

m5-credits-live-fetch: creator credits now actually arrive — fixes the
v0.5.2 known issue.

### Fixed
- **Live credit ingest** (FRG-CRTR-001/002): ComicVine only serves credits
  on per-issue detail requests (its list API returns none — the cause of
  the v0.5.2 known issue), so series refresh now fetches a bounded batch
  of issue details per run (newest first, 25 by default via
  `credits_fetch_per_refresh`, through the normal rate limit). Issues are
  marked once covered — including issues with genuinely no credits — so
  nothing refetches forever, and a failed fetch simply retries on a later
  run. Repeated refreshes (or force-running `creators-backfill`) walk the
  whole library over time.
- Test fixtures now mirror the real ComicVine shape (no credits on list
  responses) with a tripwire so this class of masking can't recur; the
  end-to-end suite proves credits render on the Creators screen.
- The README tour regains the Creators screen, captured from real
  ingested credits.

## [v0.5.2] — 2026-07-11

m5-creators-screens: the Creators pages arrive, and follows become
explicit-only.

### Added
- **Creators screen** (FRG-UI-027): a grid of everyone credited on your
  comics — roles, series counts, covers of their work in your library, and
  a Follow pill. Filter to followed creators, or arrive from a series page
  focused on just its creators. Creators joins the sidebar.
- **Creator profiles** (FRG-UI-028): roles, publishers, how much of a
  creator's work you own, and per-series role chips — each work linking
  back to its series.
- **Series credits** (FRG-UI-004): series pages show their credited
  creators, linking into the creator pages.

### Known issue
- Real-world credit ingest is currently empty: ComicVine's issue *list*
  API does not serve `person_credits` (only the per-issue detail endpoint
  does), which surfaced while capturing these screens against live data.
  The Creators pages render their honest empty state until the follow-up
  release switches ingest to per-issue detail fetches.

### Changed
- **Follows are explicit-only** (FRG-CRTR-004, owner decision): v0.5.0's
  "auto-follow anyone credited on 2+ of your series" seeding is removed,
  and follows it created are cleared on upgrade — follows you set yourself
  are untouched. Following someone is always your action, and it never
  downloads anything.

## [v0.5.1] — 2026-07-11

pull-enabled-default: the weekly-pull source is on by default.

### Changed
- **Weekly pull enabled out of the box** (FRG-PULL-002, owner decision):
  `pull_enabled` now defaults to `true`, so a fresh install's Calendar
  carries the week's releases without configuration. Set
  `pull_enabled: false` (or `FORAGERR_PULL_ENABLED=false`) to opt out —
  no third-party traffic is issued when disabled, and the calendar keeps
  working from your library's own metadata either way. A source outage
  only degrades health; it never empties the view. **Existing installs are
  not flipped**: first-run config rendering wrote `pull_enabled: false`
  into `config.yaml` under the old default, and a value present in the
  file always wins — set it to `true` (or remove the line) to enable the
  source on an install created before v0.5.1.

## [v0.5.0] — 2026-07-11

m5-creators-backbone: creator credits arrive — the data layer for M5's
creators & follows. No new screens yet; the Creators pages build on this in
the next releases.

### Added
- **Creator credits ingest** (FRG-CRTR-001): writers, artists, and the rest
  of each issue's credits now come along with ComicVine metadata — on the
  same requests foragerr already made, at no extra API cost. Names are
  sanitized like all ComicVine text; roles are normalized to a fixed set
  with the original spelling kept.
- **Creators storage** (FRG-CRTR-002): new `creators` and `issue_credits`
  tables (migration 0016), kept in sync by the normal series refresh —
  idempotent, tolerant of partial fetches, and self-pruning.
- **One-time backfill** (FRG-CRTR-003): existing libraries pick up credits
  automatically via a one-shot `creators-backfill` task (visible under
  System → Tasks, re-runnable safely).
- **Follows** (FRG-CRTR-004): each creator carries a followed flag; anyone
  credited across two or more of your series starts followed, and your own
  follow/unfollow choices are never overwritten.
- **Creators API** (FRG-API-023): `GET /api/v1/creators` (paged, with
  library stats), creator profiles, and a follow toggle — the read surface
  the upcoming Creators screens consume.

## [v0.4.7] — 2026-07-11

m4-pull-experience: the weekly pull Calendar — the final M4 chapter.

### Added
- **Calendar screen** (FRG-UI-018): a date-grouped weekly agenda of what
  ships in a store week (deliberately not a month grid — comics land in one
  Wednesday drop, badged "New Comic Day"). Week navigation with the week in
  the URL, a Following / All releases scope toggle, a publisher filter, and
  release cards with publisher-accented spines showing each issue's live
  derived state. Calendar joins the sidebar.
- **Pull entry actions** (FRG-PULL-007): want/skip and immediate search on
  calendar cards linked to library issues, delegating to the same issue
  operations the Wanted screen uses — the calendar itself stores nothing.
- **New this week** (FRG-PULL-008): unfamiliar #1/#0 debuts surface in a
  distinct strip with a one-click route into the standard add flow,
  prefilled. foragerr never adds a series by itself.
- **Future solicitations** (FRG-PULL-009): pull refresh now also fetches the
  next ISO week when the source has published it, so forward navigation
  shows what's coming, marked not yet released. A missing or failing future
  week is skipped without touching the current week's data.

### Fixed
- Pull-source text now gets the same Trojan-Source (bidi/zero-width)
  stripping at ingest that ComicVine text got in v0.4.6, before it renders
  anywhere (gate finding, RISK-039).
- WebSocket command chatter no longer re-fetches the loaded calendar week on
  every background command transition (gate finding).

## [v0.4.6] — 2026-07-11

m4-add-new: the Add New screen rebuilt to the M4 design, relevance-ranked
ComicVine search, and an add-time "Collect as" choice.

### Added
- **Relevance-ranked lookup** (FRG-META-015): ComicVine search results are
  ordered by closest title match (publication-year proximity as the tiebreak)
  instead of raw alphabetical order, so the volume you meant is normally at the
  top. Nothing is filtered out — every candidate the search found is still
  listed, ranked. Lookup and autosuggest agree on order.
- **Redesigned Add New screen** (FRG-UI-005): expandable result cards (cover,
  title/year, publisher, issue count, description, "In library" badge) with an
  inline add-config panel — root folder, format profile, monitor strategy, and
  a **Collect as** choice.
- **Add-time collected-edition typing** (FRG-SER-018): "Collect as → Collected
  Editions" locks the series book-type at add; left untouched, foragerr types
  it from the title cues as before.

### Changed
- Manual §Adding a series rewritten; README tour screenshots refreshed from a
  dedicated clean instance (the refresh tool now runs on its own port,
  FRG-PROC-017).

### Security
- The ComicVine text sanitizer (FRG-META-014) now strips Unicode
  bidirectional-override and zero-width/invisible characters, closing a
  Trojan-Source-style visual-spoofing vector on wiki-sourced text
  (RISK-011/014). No executable-XSS was reachable (output is rendered as text).

### Fixed
- An explicit `null` book-type on the add API now locks single-issues typing
  instead of being treated as omitted.
- A part-way-failed autosuggest surfaces its failure note instead of a silent
  empty dropdown.

No dependency changes.

## [v0.4.5] — 2026-07-10

roadmap-single-source: a process CAPA — forward-looking ("planned") text kept
going stale inside long-lived documents, so it now lives in exactly one place.

### Added
- **`docs/roadmap.md`** (FRG-PROC-018): the single controlled document for
  unshipped work (remaining M4 pull screen, creators, sources, torrents,
  authentication). Other documents link to it instead of restating plans.
- **Merge-gate roadmap checks** (FRG-PROC-018): the test suite now fails if
  forward-milestone tokens or planned-phrasing appear in the README or manual
  outside the roadmap, or if the roadmap advertises an already-implemented
  requirement as planned — shipping a roadmap item forces the roadmap update
  in the same change.

### Changed
- **README Roadmap section** (FRG-PROC-014) is now a pointer to
  `docs/roadmap.md` rather than a list that rots.
- **Manual sweep** (FRG-PROC-011): forward references ("before M8", "later
  milestone", post-auth phrasing) reworded to current-state descriptions with
  roadmap links (network, deployment, secrets, configuration, OPDS, metadata
  pages); the manual's currency statement brought up to v0.4.x reality.

### Fixed
- The README no longer lists the largely-shipped M4 design refresh as
  "planned, not yet shipped", and the planned torrent client is correctly
  stated as qBittorrent (per FRG-TOR-002) instead of Transmission.

No runtime behavior changes; no dependency changes.

## [v0.4.4] — 2026-07-10

m4-series-detail: the series detail screen rebuilt to the M4 design, plus the
trade "collected in" containment model.

### Added
- **Redesigned series detail** (FRG-UI-004): a hero with the cover blurred
  into the backdrop, the sharp cover beside title/meta (monitored, publisher,
  first issue, status, count, formats), an icon action row — Search
  Monitored, **Search All** (now genuinely searches every missing issue
  regardless of monitored state, FRG-SRCH-008), Refresh, Edit, Delete, and a
  ⋯ overflow keeping Rescan and Rename Files — and a long overview collapsed
  behind "show more". Below, an Issues/Collections panel with a compact
  progress bar.
- **Bulk issue actions** (FRG-UI-025, owner request): row checkboxes with
  shift-click range selection, header select-all, and a labeled action bar —
  Monitor, Unmonitor, Search selected (sequential, duplicate-click guarded,
  partial failures reported) — replacing the old unlabeled header button.
- **Trade containment** (FRG-SER-020/API-022/UI-026): declare which issues a
  collected edition collects (dialog with per-range target and issue
  pickers; multiple sub-ranges; edit pre-fills what's declared and save
  replaces it wholesale — stated in the dialog). The Issues tab shows
  "Collected in" chips; the Collections tab shows both directions — what
  collects this series, and what a trade's own books declare — with
  Collected / Partial / Not collected coverage pills computed from files on
  disk. **Display-only by construction**: the wanted machinery provably
  never reads containment (the never-suppress invariant's absence proof now
  covers the new table).

### Fixed
- Dialogs on the detail screen (Delete, Delete File, Edit, containment) now
  trap and restore focus, close on Escape, and announce errors — via the
  shared modal.
- Fileless issues with no dates now read Missing (matching what the wanted
  set says) instead of a neutral Unreleased pill.
- Navigating series → series (e.g. via a Collections "Open") resets
  selection, tab, and command status; segmented controls gained proper
  arrow-key behavior.
- The grouped-library franchise ⋯ popover mirrors the shared menu's focus
  and Escape behavior (ch2 review deferral closed).

### Notes
- Migration 0015 (`issue_collections`, additive). Threat model/risk register
  record the new containment write surface (T-API-8, RISK-044; RISK-020
  no-auth lineage). Manual documents the screen and the declare/edit flow.
  No new dependencies. Derived containment suggestions from ComicVine
  descriptions are deliberately out — our sanitizer strips the structured
  links at ingest; the schema carries provenance columns so suggestions can
  land later without a migration.

## [v0.4.3] — 2026-07-10

m4-logs-viewer: in-app log visibility for debugging acquisition (owner request).

### Added
- **System → Logs screen** (FRG-UI-024): a dense live view of the backend's
  recent log records — time, level pill, logger, message — with minimum-level
  and logger-prefix filters and a **Follow** toggle that tails the newest
  records (polling; stops when off or when you leave the screen). Honest
  empty/error states.
- **Log records API** (FRG-API-021): `GET /api/v1/log` serves a bounded
  in-memory ring buffer of recent records, paged newest-first with level and
  logger filters. Records pass the secret-redaction filter *before* they can
  be buffered, so the endpoint can never serve an unredacted registered
  secret — proven by tests covering direct, `%s`-args, exception-traceback,
  and logger-name paths.
- **Retention setting** (FRG-NFR-015): `FORAGERR_LOG_BUFFER_RECORDS`
  (default 2000) bounds the buffer; per-record messages are capped
  server-side. Memory-only — a restart clears the buffer; container stdout
  remains the durable log.

### Notes
- Threat model + risk register updated for the new read surface (T-API-7,
  RISK-043). A durable access/audit log is deliberately deferred to the auth
  milestone and recorded as such. No dependency changes. Review-gate note:
  first change run under the tiered-gate policy (small + security-touching:
  three targeted angles including a dedicated secret-leak adversary, plus
  the independent-model review).

## [v0.4.2] — 2026-07-10

m4-library-views: the library index rebuilt to the M4 design — three views,
raised menus, and a live-demo feedback round.

### Added
- **Three library view modes** (FRG-UI-003): Posters — a responsive grid with
  S/M/L sizes and full card anatomy (monitored bookmark, publisher chip,
  publisher-tinted cover fallback, owned/total progress strip, status/year
  subline); Overview — rows with a cover thumb, status pill, wide progress bar
  and percent complete; Table — dense monitor/Title/Publisher/Issues/Status/
  Year columns. A count line reads `N comics · N monitored · N with missing
  issues` in semantic colors.
- **Toolbar menus** (FRG-UI-003): a view switcher plus Options (poster size,
  group-volumes toggle), Sort (Title/Publisher/Issues owned/Year, check on
  active — disabled while grouping, which it cannot order), and Filter
  (All/Monitored/Missing issues/Continuing with live counts, plus an EDITIONS
  section carrying the collected-editions filter, FRG-UI-022). A content click
  closes an open menu without activating what's beneath it. View mode, poster
  size, sort, and both filters persist across sessions.
- **Stacked franchise cards** (FRG-UI-021): in grouped poster mode a
  multi-volume franchise is one layered-shadow card with an `N vols` chip and
  summed owned/total; Overview/Table keep collapsible franchise headers. The
  rename/detach affordance (FRG-SER-017) remains reachable everywhere.
- **The brand mark** (FRG-UI-023): the sidebar lockup now renders the real
  ant-in-hexagon SVG mark to the handoff's exact spec, links back to the
  library, and the app ships an SVG favicon.

### Fixed
- After adding a series, its issues now appear as the background refresh
  lands them — the WebSocket bridge invalidates the issues cache alongside
  the series caches (FRG-UI-001; owner-reported from the live demo).
- Cover art cached or replaced by a refresh now appears without a hard
  reload — cover URLs are versioned by the cache timestamp, and a series
  without a cached cover renders its tint fallback instead of a broken
  image (FRG-UI-003/004; owner-reported).
- Review-gate round (8 angles + Codex): the stacked card's menu is now
  keyboard-reachable (its cover/title became a real link, the menu a
  focusable sibling); Sort/Filter options announce their active state to
  assistive tech; the Options panel no longer claims menu semantics for its
  controls and focuses on open; result changes are announced politely; and
  large-library typing cost dropped (memoized sort/join, gated filter
  counts, memoized cards).

### Notes
- Frontend-only; no API, schema, or SOUP changes. The old alphabet jump bar
  and stats footer are superseded by the count line and menus. The manual's
  library page documents the new controls.

## [v0.4.1] — 2026-07-10

m4-shell-hotfix: tour rendering defects found post-v0.4.0.

### Fixed
- Series-detail cover art renders whole again: the hero row's flex-stretch was
  defeating the poster frame's 2:3 aspect once a series description got long
  (latent since change 7), cropping the cover to a zoomed slice.
- The README tour is now deterministic: the refresh tool applies known
  demo-library match overrides (Planet Comics → the 1940 Fiction House volume)
  and fails loudly if an override target is missing — a fresh tour database
  had silently matched the 1988 Blackthorne reprint. Tour regenerated.

## [v0.4.0] — 2026-07-10

m4-design-shell: the M4 design refresh begins — new design language and app shell.

### Added
- **New app shell** (FRG-UI-023): 212px sidebar with the Foragerr lockup, grouped
  navigation with live count badges (Comics, Queue, Wanted in warn style),
  Settings/System sections, and a health-pulse footer showing the running
  version — with honest connection reporting ("reconnecting…" text + live
  region when the WebSocket drops) and a skip-to-content link. 60px global
  header with the library quick-search and Health/System buttons. Content is
  the single scrolling region.
- **One-command README screenshot refresh** (FRG-PROC-017):
  `tools/refresh-readme-shots.sh` regenerates the README tour against the
  public-domain demo library — with stale-port and partial-import guards —
  and every UI-affecting change re-runs it before merging. This release's
  tour already shows the new interface.

### Changed
- **Design tokens rebuilt** (FRG-UI-002): dark warm-neutral surfaces, the
  green accent family, semantic status and progress colors, publisher and
  format-chip palettes as data; Roboto and Font Awesome 6 self-hosted — the
  app makes no font/icon CDN requests, and non-woff2 fallbacks are dropped
  from the bundle (~516 KB smaller).
- Calendar and Creators do not appear in the navigation yet — nav lists
  shipped screens only; they arrive with their screens (M4 ch5, M5).

### Notes
- SOUP register gains @fontsource/roboto (OFL-1.1) and
  @fortawesome/fontawesome-free (CC-BY-4.0/OFL-1.1/MIT), both bundled static
  assets. Screens' behavior is unchanged — redesigns of the individual
  screens land through the rest of M4.

## [v0.3.7] — 2026-07-10

roadmap-reshape: M4 design refresh · M5 creators · M6 sources · M7 torrents · M8 auth.

### Changed
- **Roadmap reshaped** (owner-approved): M3 closes by rescoping the pull
  experience to M4; M4 = design refresh (new app shell and tokens, library
  views, series detail with trade containment, add-new, the pull experience,
  screenshot-refresh tooling); M5 = creators & follows; M6 = sources — an
  encrypted credential store lands first (key from environment only, never a
  file — FRG-AUTH-008), then the Humble Bundle importer, then archive.org;
  M7 = torrents (Transmission-first, Torznab-only indexing via
  Prowlarr/Jackett, per-torrent ratio/seed-time limits); M8 = authentication,
  which requires fresh owner approval to begin.
- **README is a controlled document** (FRG-PROC-011 modified): any change that
  alters a fact the README states updates it in the same change, and a
  doc-consistency test pins roadmap milestone labels to the registry.
- **Codex made the official ninth review perspective** at every merge gate
  (checklist item 6).
- Stale pre-reshape milestone claims swept repo-wide: the manual, threat
  model, risk register, decisions index, and the FRG-AUTH-001 requirement
  text now state the M6/M8 boundaries; RISK-020 records the owner's conscious
  re-acceptance of the no-auth posture through M7.

### Notes
- Planning/process/labelling docs only — no application behavior changes.
- Design handoffs are gitignored as a class (including `.dc.html` exports).

## [v0.3.6] — 2026-07-10

known-anomalies: a known-anomalies register (FRG-PROC-016), seeded with KA-001.

### Added
- **Known-anomalies register** (`docs/security/known-anomalies.md`): every
  anomaly the owner accepts rather than fixes gets a stable, never-deleted
  `KA-NNN` entry — description, impact evaluation, owner decision with
  rationale, mitigations, review trigger — consistency enforced by tagged
  tests (FRG-PROC-016).
- **KA-001** (this release accepts it): an un-revocable ComicVine API key sits
  in public git history inside a design-exploration export (all tags
  v0.1.0–v0.3.5). Accepted 2026-07-09 after evaluation — free rate-limited
  key, no billing/PII/account surface, provider offers no rotation, history
  rewrite rejected as disproportionate. Full record and review triggers in
  the register.
- **`.gitleaks.toml`** with a `bare-key-hex` rule closing the detection gap
  that let the KA-001 class through three scanners; the merge-gate history
  scan now runs with this config and demonstrably surfaces the KA-001 blob.

### Changed
- `docs/security/history-scan.md` corrected (its blanket no-credential claim
  was falsified by KA-001) and RISK-042 records the residual; RISK-041 now
  carries the owner's direction that the future at-rest encryption key
  (FRG-AUTH-008) is supplied via the environment only, never a file.
- The key-bearing design export is removed from the working tree (the
  historical blob remains, accepted); design handoffs stay out of the
  repository and `.gitignore` guards the class.

## [v0.3.5] — 2026-07-10

ddl-optin-seeding: the first-run DDL provider pair now ships disabled.

### Changed
- **Fresh installs no longer acquire anything on their own.** First-run
  seeding still creates the GetComics indexer and built-in DDL client rows —
  pre-configured and visible in Settings — but both ship **disabled**, with
  the indexer's automatic-search/RSS toggles off. Enable the pair (Settings →
  Indexers, Settings → Download Clients) to start acquiring; one toggle each,
  no other configuration (FRG-DEP-013).
- Existing installs are untouched: rows seeded enabled under the old posture
  stay enabled, and the never-resurrect / never-inject rules are unchanged.
- RISK-015/RISK-016 posture returns from default-enabled to opt-in; the
  triggering event (a fresh demo install auto-grabbing live downloads within
  a minute of a library import creating wanted issues, 2026-07-09) is
  recorded in the risk register and threat model.

### Fixed
- The image-build secret scanner no longer false-positives on code
  identifiers shaped like `comicvine_api_key: ComicVineKeyStatus` — the
  generic rule now requires a digit-bearing value, while still reporting a
  line that carries both a benign identifier and a real secret.

### Notes
- No dependency changes; no new attack surface (the default surface strictly
  shrinks).

## [v0.3.4] — 2026-07-09

going-public: the repository is opened to the public. A docs/process/labelling
change — no application behavior changes.

### Added
- **GPL-3.0 license**: verbatim GPL-3.0 text as `LICENSE`, declared in
  `pyproject.toml` and the README labelling (FRG-DEP-014).
- **README tour**: screenshots of the main screens (captured from a demo library
  of public-domain golden-age comics), each captioned with links to the governing
  requirement IDs, spec, and manual page (FRG-PROC-014).
- **History hygiene evidence**: full-git-history secret scan (gitleaks) recorded
  in `docs/security/history-scan.md` — 0 unresolved findings; the record is
  re-affirmed before any history-affecting push (FRG-PROC-015).

### Changed
- README rewritten as public labelling: owned-library lead, content-neutral
  acquisition description, explicit Roadmap for unshipped work, and the
  source-available contribution posture (FRG-PROC-014).
- Private/never-released framing removed from `CLAUDE.md`, the manual index, and
  this changelog's preamble; RISK-015/RISK-020 rationales reworded to rest on the
  deployment posture (repository visibility was never a compensating control) —
  acceptances, owners, and review triggers unchanged.

### Notes
- No dependency changes (gitleaks is a development-time gate tool, not SOUP).
- The GitHub visibility flip itself is the owner's manual action after this
  release's merge gate passes.

## [v0.3.3] — 2026-07-08

M3 change 5: collected-edition (trade) typing.

### Added
- **Collected-edition typing**: foragerr now recognises a trade paperback / graphic
  novel / hardcover series from its title and shows a **TPB / GN / HC badge** on the
  series card (in the library grid, the table view, and inside a franchise group) and
  on the series-detail page. A library **filter** shows only collected editions, only
  single-issue runs, or everything. You can set a series' type explicitly when editing
  it; your choice survives metadata refreshes (FRG-SER-018, FRG-UI-022).

### Notes
- **Owning a trade never affects your single issues** — this is a guaranteed,
  dedicated invariant (FRG-SER-019): single issues and collected editions are
  independent tracks, so typing a series or owning a full trade line never marks a
  single issue owned and never removes a missing single issue from wanted/searchable.
  It is enforced structurally (no book-type predicate in the wanted/statistics
  computation; a trade's files belong to the trade series) and proven by tests.
- No new dependency, no new attack surface. Database migration 0014 adds the series
  `booktype` columns. "Collected in" containment linkage and book-type-aware search
  filtering are deferred to the backlog. Gate: 8 review angles + Codex (invariant a
  named angle) → fixes applied; backend 1626 passed, frontend 251 passed.

## [v0.3.2] — 2026-07-08

M3 change 4: volume grouping.

### Added
- **Franchise grouping** on the Comics screen: foragerr now groups a title's
  successive runs ("Batman (2011)", "Batman (2016)", …) into one franchise. A
  **Group** toggle switches between the flat series list and a grouped view where each
  franchise is a collapsible header with an owned/total issue roll-up and its runs
  nested beneath. Grouping is derived automatically from the series title (trailing
  volume year / `Vol N` stripped) and is **display-only** — it never changes what a
  series is, how it's monitored, or which issues are wanted (FRG-SER-016, FRG-UI-021).
- Correct a wrong grouping from a franchise's menu: **rename** a group (the name
  survives metadata refreshes) or **detach** a run (its choice is locked so a later
  refresh won't re-group it) (FRG-SER-017).
- `GET /api/v1/series/groups` returns the franchise projection with a bounded,
  single-query stat roll-up; the flat `GET /api/v1/series` gains each series'
  `series_group_id` (FRG-API-020).

### Notes
- Grouping adds no new dependency and no new attack surface. Database migration 0013
  adds the `series_groups` table and two additive series columns. A test proves
  `wanted_issues`/`series_statistics` output is byte-identical before and after
  grouping. Gate: 8 review angles + Codex → fixes applied; backend 1595 passed,
  frontend 245 passed.

## [v0.3.1] — 2026-07-08

M3 change 3: OPDS page streaming (the reading upgrade).

### Added
- **OPDS-PSE page streaming**: PSE-capable readers (Panels, Chunky) can now open a
  comic and stream it **one page at a time** instead of downloading the whole file
  first. Every issue advertises page streaming **alongside** the existing whole-file
  download, so a non-streaming reader is unaffected. Pages stream in natural reading
  order and a reader can request a reduced width to save bandwidth (FRG-OPDS-008,
  FRG-OPDS-010).
- **Cached page counts**: an issue's page count is computed once at import (from the
  archive scan the pipeline already does — no extra work) and cached, so browsing the
  catalog stays fast and opens no archives at render time; a legacy issue's count is
  filled in on first access (FRG-OPDS-009).
- **Local covers with no external egress**: an issue with no ComicVine cover now shows
  a cover generated from its own first page (extracted, resized, cached), and all
  cover/thumbnail images are served by foragerr itself — your reader never reaches out
  to a third-party image host to show a cover (FRG-OPDS-011).

### Security
- The new server-side archive-open and image-decode paths (the only untrusted-archive
  decode surface on the OPDS listener) enforce configurable resource limits — archive
  member count, per-page decompressed size (checked before read), image pixel count
  (checked before decode; truncated-image loading disabled), a per-request time bound,
  and a bounded number of concurrent decodes — so a crafted zip-bomb or pixel-bomb in
  the library degrades to a bounded error instead of exhausting memory or CPU. RISK-005
  is closed and RISK-010's cover-extraction arm is live (FRG-OPDS-012).

### Notes
- **CBR (`.rar`) comics** are downloaded whole as before but are **not** page-streamed
  (foragerr does not bundle an unrar tool); keep a title as `.cbz` for streaming.
- New admin settings `opds_pse_max_members`, `opds_pse_max_page_bytes`,
  `opds_pse_max_pixels`, `opds_pse_max_width`, `opds_pse_request_timeout_seconds`
  (see the admin manual). Adds the **Pillow** image library (used only on these OPDS
  decode paths). Database migration 0012 adds `issue_files.page_count`. Gate: 8 review
  angles + Codex → fixes applied; backend 1569 passed / 10 skipped.

## [v0.3.0] — 2026-07-08

M3 change 1: weekly-pull backbone. **Begins milestone M3 ("comics-native")** — the
data, jobs, and read API beneath a weekly pull list (the screen itself is M3 change
2). Backend only; the external pull source is opt-in and off by default.

### Added
- Metadata-derived weekly release view: for a store-date week, the issues of watched
  series dated in that week, each with derived state (missing/wanted, downloading,
  downloaded, unmonitored) computed from issue + queue records — works with no
  external source configured (FRG-PULL-001).
- `GET /api/v1/pull?week=` read endpoint backing the view: standard paging envelope,
  per-entry match type and linked-issue state, prev/current/next week by parameter,
  read-only, no secret exposed (FRG-API-019).
- External weekly-pull source fetch (opt-in; `pull_enabled` off by default): the
  walksoftly / League-of-Comic-Geeks JSON API fetched over the hardened external
  egress profile (current + previous week, mandatory timeouts, auto-redirect
  disabled), parsed as untrusted JSON under byte caps; documented source codes
  handled (619 skips a week; 522/666/transport → a source-outage that leaves stored
  data intact and marks the source **degraded** in health) (FRG-PULL-002).
- Idempotent per-week storage: a `pull_entries` table with per-week
  replace-on-refresh, so a re-fetch is idempotent and a mid-run failure leaves the
  prior week intact; entries carry a link to a library issue and a match type, never
  their own wanted/downloaded status (FRG-PULL-003, migration 0011).
- Matching pull entries to the library: ComicVine-id match first (book-type guarded),
  else a guarded name match (normalized name/alias equal, 0 ≤ sequence delta < 3, and
  release date within the pull week ±2 days); ambiguous/unknown entries stay
  unmatched; an unmatched new #1/#0 is tagged as a new-series candidate. Only watched
  (monitored) series are matched (FRG-PULL-004).
- Refresh trigger for missing pulled issues: a matched-but-missing issue enqueues the
  existing `refresh-series` command (deduplicated on the queue), so metadata creates
  the issue and the series' monitor policy decides whether it becomes wanted — the
  pull side writes no issue status (FRG-PULL-005).
- Scheduled + manual pull refresh: a built-in `pull-refresh` task (default 4 h,
  clamped up to a 1 h floor) that fetches → stores → matches → triggers; a manual
  force-run bypasses the interval gate; runs recorded in history and pushed over the
  WebSocket (FRG-PULL-006).

### Security
- RISK-039 mitigation realised (timeouts, documented error-code handling,
  degraded-health, untrusted-JSON) and the pull-source arm of RISK-025 closed via the
  external egress profile (see the threat model and risk register).

Upgrade notes: new admin settings `pull_enabled` (default off), `pull_source_url`,
and `pull_refresh_interval_seconds` (see the admin manual "Weekly pull" section);
database migration 0011 adds the `pull_entries` table. Test status at merge:
backend 1513 passed / 10 skipped.

## [v0.2.8] — 2026-07-06

M2 change 6: hardening and performance. **Completes milestone M2 ("own your
library")** — v0.2.0..v0.2.8, 7 changes plus 2 owner-driven insertions.

### Added
- Listener resource limits: HTTP request body/header size caps (streamed and
  aborted at the cap, never buffered whole), request timeouts, and a per-client
  rate/concurrency cap; a WebSocket connection cap and inbound-frame size/rate
  limits on the drain loop (FRG-NFR-014, RISK-021 mitigated).
- Startup-time budget benchmark (5,000-issue seed, p95 over N starts) with a
  no-outbound-network-at-startup guard and an isolated-importability regression
  test (FRG-NFR-001).
- Scan-throughput benchmark (5,000 files under a 10-minute budget) and a UI-latency
  benchmark (p95 < 500 ms on key read endpoints), each with always-on structural
  guards (FRG-NFR-002, FRG-NFR-003).
- Crash-safe/idempotent-work fault-injection tests (kill-and-restart at
  post-enqueue, mid-download, and pre-import-commit) confirming no lost acknowledged
  item, no duplicate snatch, and no duplicate library rows (FRG-NFR-007).

### Security
- Request-sourced values written to structured logs are now bounded and
  CR/LF-sanitized, preventing a forged/injected log line (RISK-014, request arm).

Test status at merge: backend 1440/10, frontend 234, e2e 13+1 skipped, all green.

## [v0.2.7] — 2026-07-06

M2 change 5.5: config hygiene and first-run defaults.

### Changed
- Removed the three unused global credential fields (`dognzb_api_key`,
  `nzbsu_api_key`, `sabnzbd_api_key`) from settings; an existing config file that
  still carries them loads fine with a logged warning. Per-provider credentials are
  unaffected (FRG-DEP-003).

### Added
- ComicVine API key is now configurable from **Settings → General**: a masked field,
  a connectivity "Test" button, live apply without a restart, and honest reporting of
  whether the key is unset / set-in-file / set-by-environment (FRG-API-018,
  FRG-META-002, FRG-UI-020).
- Fresh installs now seed one enabled GetComics DDL indexer and one enabled built-in
  DDL download client, so a keyless search → grab → download pipeline works out of the
  box; an existing install is marked seeded without having providers injected
  (FRG-DEP-013).

Test status at merge: backend 1369/7, frontend 234, e2e 13+1 skipped, all green.

## [v0.2.6] — 2026-07-06

M2 change 5: ops, health, and backups.

### Added
- Scheduled database + config backups: full integrity check, WAL checkpoint, and a
  consistent SQLite-API backup (never a raw file copy) written to
  `/config/backups/scheduled-<timestamp>/`, with rolling retention; runnable on
  demand via "Back up now" (FRG-DB-009).
- Startup `PRAGMA quick_check` and a full `PRAGMA integrity_check` before every
  scheduled backup; a failure surfaces as a persistent health error and aborts the
  backup rather than overwriting the retained set (FRG-DB-012).
- Marker-driven startup restore: validate a chosen backup, snapshot the current
  database aside, swap the backup in, and clear the marker — all with the database
  closed (FRG-DB-010).
- `GET /api/v1/system/health`, `GET /api/v1/system/task`, and
  `POST /api/v1/system/task/{name}` (force-run), plus an extended
  `GET /api/v1/system/status` (FRG-API-014).
- System area in the UI: Status, Health (per-component state with remediation hints),
  and Tasks screens with per-task force-run (FRG-NFR-011, FRG-UI-016).

RISK-041 accepted (see risk register). Test status at merge: backend 1341/7,
frontend 221, e2e 13+1 skipped, all green.

## [v0.2.5] — 2026-07-06

M2 change 4.5: search autosuggest and quick-search.

### Added
- Bounded ComicVine "suggest" endpoint returning only the first page of results,
  distinct from the full paginated lookup (FRG-API-017).
- Add Series screen gains a debounced, cancellable autosuggest dropdown (fires after
  ≥3 characters) backed by the suggest endpoint (FRG-UI-005).
- Global header quick-search over locally cached series titles/aliases (no network
  request per keystroke), keyboard-navigable, with a "Search ComicVine for '…'"
  fall-through into Add Series (FRG-UI-019).

Also closes deferred e2e coverage for the History/Wanted/OPDS-Recent daily spine.
Test status at merge: backend 1298/7, frontend 204, e2e 13+1 skipped, all green.

## [v0.2.4] — 2026-07-06

M2 change 4: daily-use surfaces.

### Added
- History screen: single-source, deduplicated event feed over `import_history` with
  series/issue filters (FRG-API-011, FRG-UI-010).
- Wanted screen: paged missing-issues list with per-issue interactive search and a
  search-all action (FRG-API-012, FRG-UI-011).
- Blocklist screen: view blocked releases with the reason they were banned, and
  remove a release to make it grabbable again (FRG-UI-017).
- Root-folder management: `POST`/`DELETE /api/v1/rootfolder`, plus a Root Folders
  section in Media Management settings — previously a fresh install had no way to add
  a root folder at all, making series/download/import unreachable on first run
  (FRG-SER-008, FRG-UI-012).
- Delete-files support: series deletion with `deleteFiles=true` now actually deletes
  (routed through the recycle bin) instead of returning 501; new per-issue-file delete
  action (FRG-API-003, FRG-UI-004).
- OPDS Recent Additions feed and an OpenSearch-backed catalog search feed
  (FRG-OPDS-013, FRG-OPDS-007).

### Fixed
- An identical import-blocked outcome on retry no longer writes a duplicate history
  row each retry cycle (RISK-040, mitigated).
- The "started" command-status transition now pushes over the WebSocket like the
  queued/terminal transitions already did (FRG-SCHED-010).

### Changed
- The cutoff-unmet half of the Wanted requirement was dropped from this release per
  the owner's M2 reshape (quality cutoffs parked to backlog).

## [v0.2.3] — 2026-07-06

M2 change 3: existing-library import.

### Added
- Library Import screen: pick a root folder, scan it, review per-group ComicVine match
  proposals (confidence, poster, year, issue counts), correct via the existing lookup,
  then bulk-import — series are created with existing files already registered, no
  downloads triggered (FRG-IMP-023, FRG-UI-015).
- Root-folder scan gains junk-aware skipping (AppleDouble/`@eaDir`, resource forks,
  dotfiles, zero-byte files, unpack-temp folders) and DB-vs-disk reconciliation,
  generalized from the per-series rescan (FRG-IMP-022).
- Configurable duplicate-file arbitration: preferred-format-or-larger-size tie-break
  for same-rung duplicates (profile-order upgrades still decide first); fixed-release
  markers always win; the losing file can move to a dated duplicate-dump folder
  instead of being deleted (FRG-PP-014).

## [v0.2.2] — 2026-07-06

M2 defect fix: lookup auth-error surfacing.

### Fixed
- Add Series no longer silently shows an empty "no results" state when the ComicVine
  API key is missing or invalid; a distinct error state names the credential problem
  instead (FRG-META-004, FRG-API-003, FRG-UI-005).
- Lookup responses now expose `complete`/`truncated` flags so a degraded partial
  result, a capped result, and a clean empty result are distinguishable from one
  another.
- Re-running a search with the same term always issues a fresh lookup rather than
  reusing a stale error/result state.
- The add-series flow surfaces the same credential guidance (instead of a generic
  failure message) when the existence check hits a ComicVine auth error.

## [v0.2.1] — 2026-07-06

M2 change 2: manual import and ComicInfo metadata.

### Added
- Manual import: resolve candidate files (from an import-blocked download or an
  arbitrary folder) with per-file series/issue/format overrides, executed through the
  same pipeline, evidence layer, and safety rails as automatic import — no parallel
  code path (FRG-PP-016, FRG-API-015, FRG-UI-014).
- Embedded ComicInfo.xml (and embedded ComicVine issue ids) is read at import time and
  preferred as evidence over filename parsing when verified (FRG-IMP-024).
- Optional in-process ComicInfo.xml tagging of cbz archives on import, off by default,
  routed through the shared archive-safety layer (FRG-PP-017).

### Fixed
- WebSocket endpoint teardown no longer attempts to re-close a socket the client has
  already closed.

## [v0.2.0] — 2026-07-06

M2 change 1: naming control, rename preview, and recycle bin.

### Added
- Rename preview: compute existing-path → new-path previews for any series/file
  selection under the current naming templates, without touching disk; execution is
  an explicit second step (FRG-PP-012).
- Recycle bin: a configurable directory for upgrade-replaced files and user-initiated
  deletions, replacing M1's fixed quarantine folder, with retention pruning
  (FRG-PP-013).
- Settings → Media Management screen: file/folder naming templates with token help and
  a live rename preview against a real series (FRG-UI-012).
- Config resource endpoints backing the naming/media-management settings screen
  (FRG-API-013).

### Changed
- `config.yaml` gains a schema version; startup migrates older config files forward
  (with the same pre-migration backup discipline the database already had) and refuses
  newer-than-supported files (FRG-DEP-004).

## [v0.1.1] — 2026-07-06

M1 acceptance-certified. **Completes milestone M1** (acceptance sign-off recorded in
the archived change-8 proposal).

### Added
- Playwright end-to-end verification harness exercising the full M1 slice against the
  real container image, with external services mocked by default and optionally live
  via env-gated credentials: add a series, interactive search with rejection reasons,
  grab → download → automatic import → renamed file in the library, series browse in
  the UI, and OPDS feed navigation/download with correct MIME type (FRG-PROC-010).

### Changed
- The M1 acceptance layer is generated directly from FRG-tagged e2e results rather
  than a hand-authored criteria matrix: 8 pass / 1 skipped (live tier) / 0 flaky /
  0 not-run, rolling up 19 FRG requirements.

## [v0.1.0] — 2026-07-06

M1 feature-complete: the full vertical slice from filename parsing through metadata,
search, download, import, UI, and OPDS.

### Added
- Foundational backend: single SQLite database with WAL mode and forward-only
  migrations, a persisted background-command scheduler with priority/exclusivity
  groups and an in-process event bus, structured logging, an unauthenticated
  `/health` liveness endpoint, and a shared outbound HTTP client with SSRF egress
  controls (FRG-DB-001..008, FRG-SCHED-001..011, FRG-DEP-002,003,005..010,
  FRG-SEC-001).
- Deterministic filename parser: issue numbers (including decimals, suffixes, ranges),
  volumes, years, annuals/specials, and scan-group/edition tags, validated against a
  75-row corpus and ~4.6k real filenames (FRG-IMP-001..021).
- Library management: series/issue tracking keyed to ComicVine volume/issue ids,
  two-level (series and issue) monitoring, root folders with templated paths, format
  profiles, and ComicVine metadata refresh with rate limiting, offset pagination, and
  local cover-art caching (FRG-SER-001..014, FRG-META-001..014, FRG-QUAL-001..002).
- Newznab indexer support (RSS, automatic, and interactive search) with a decision
  engine that surfaces every accept/reject outcome and its reason, cross-indexer
  de-duplication, and hardened/defused XML parsing (FRG-IDX-001..010,
  FRG-SRCH-001..014, FRG-SEC-002).
- Downloading via SABnzbd and a built-in DDL client (GetComics), with a
  tracked-download state machine, automatic blocklisting, and re-search on failure
  (FRG-DL-001..013, FRG-DDL-001..013).
- Shared import pipeline: multi-source evidence aggregation, archive validity/safety
  checks (zip-slip protection, size/nesting caps), safe file operations, token-based
  renaming with a round-trip guarantee, and import history (FRG-PP-001..011,
  FRG-SEC-003..004).
- React + TypeScript web UI: library grid/table, series detail with per-issue
  monitoring, add-series lookup, a live (WebSocket-pushed) queue, an interactive search
  overlay showing every decision, and schema-driven provider settings forms
  (FRG-UI-001..009, FRG-API-010).
- OPDS 1.2 acquisition catalog for reading over Tailscale: navigation root, per-series
  feeds built entirely from database fields, library-id-only file resolution, correct
  comic MIME types, and paginated feeds (FRG-OPDS-001..006).
- Single linuxserver.io-convention Docker image (PUID/PGID, `/config` volume,
  s6-overlay-compatible init, HEALTHCHECK, port 8789) with the frontend built in and
  served by the backend (FRG-DEP-001, FRG-DEP-011).

### Security
- No authentication on any surface by design, with the risk explicitly accepted and
  documented (RISK-020); the deployment model is Tailscale-only exposure with no
  built-in HTTPS termination (FRG-AUTH-001).
