# m8-auth-core — design

Inherits the m8-auth pre-design (branch `change/m8-auth`, ded296c) as design
authority; this document scopes it to the core change and fixes the decisions
implementation needs. Where the two differ in detail, this file wins for this
change.

## Context

Surfaces at implementation time (post-v0.6.3): `/api/v1/*` routers, `/opds`,
the SPA mounts, `/health`, and the WebSocket — all unauthenticated under
FRG-AUTH-001's accepted risk, with route-boundary tests already pinning the
listener surface. The M6 keystore supplies `cryptography` (scrypt),
fail-fast-on-missing-env precedent (FRG-AUTH-011), and redaction registration
(FRG-NFR-008). The spec baseline (AUTH-002/003/004/010, SEC-005) fixes most
shape; the pre-design's owner decisions fix the rest.

## Goals / Non-Goals

**Goals:** one unconditional default-deny perimeter; all three credential
*verifications* live so every surface has a working path on day one; comfort
engineered in (remember-me) rather than bypassed; the uniform-coverage
invariant provable three ways.

**Non-Goals:** credential lifecycle UI (key rotation/display, OPDS password
change — `m8-keys-opds`); rate limiting/lockout/audit events
(`m8-rate-audit`); multi-user, OIDC, 2FA, scoped keys, TLS (backlog/DEP);
login-screen visual polish (M9).

## Decisions

### 1. Perimeter: default-deny by construction

A single auth dependency at the application root (router-level dependency on
every mount), not per-route decoration — routes are *born* protected;
exemption is the explicit act. Exempt list fixed at exactly: `/health`, the
login route, login static assets (the SPA shell + assets needed to render the
login screen — served unauthenticated; every API call the shell makes is
authenticated, so the shell itself discloses nothing but static UI code).
Three-way FRG-AUTH-010 proof:
(a) construction — dependency above all routers, new routers covered by
default; (b) exhaustive route-inventory test walking `app.routes`, asserting
every route is exempt-listed or refuses bare requests (401/403);
(c) e2e negative paths on each surface (UI, API, OPDS, WS) per the UAT
negative-paths rule. The WS handshake runs the same dependency (session or
API key) plus the SEC-005 Origin check and refuses pre-upgrade.

*Alternative rejected:* per-route decoration (the Sonarr-ish pattern) — the
classic forgot-the-dependency regression is exactly what AUTH-010 exists to
prevent.

### 2. One principal, three credentials, one table

| Surface | Credential | Transport |
|---|---|---|
| Web UI (SPA + its API calls) | form login → session cookie | HttpOnly SameSite=Lax cookie |
| Programmatic API | generated API key | `X-Api-Key` header ONLY (no query param) |
| OPDS (iPad readers) | HTTP Basic, own realm | `Authorization: Basic`, own KDF hash |

This change ships *verification* for all three (the perimeter is incoherent
otherwise: default-deny with no credential path would brick OPDS/API until
the next release). `m8-keys-opds` ships lifecycle: display-once, rotation,
independent OPDS password change in Settings. OPDS password seeded at
bootstrap from `FORAGERR_OPDS_PASSWORD` when provided, else equal to the
admin password — AUTH-005's independence arrives with its lifecycle change;
AUTH-005/006/007 flip there. API key: 256-bit random, stored SHA-256
(high-entropy input needs no KDF), surfaced once at bootstrap (log-safe
mechanism: written to a bootstrap notice in the UI after first login — never
to logs; decided here, displayed in Settings by `m8-keys-opds`). The SPA
never sees or uses the API key.

### 3. Passwords: scrypt (owner amendment to AUTH-003)

`cryptography`'s scrypt, per-credential 16-byte salts, parameters sized to
~100–250 ms verify on target hardware (higher n than the keystore's
interactive profile; constants recorded with a rationale comment; benchmark
at impl). Constant-time comparison. Passwords never logged; bootstrap env
values redaction-registered for the process lifetime (keystore precedent).

### 4. Sessions: DB-backed opaque tokens, two tiers

`sessions` table: token **hash** (SHA-256 of a 256-bit random token; raw
token only ever in the cookie), principal, created/last-seen, tier, expiry.
No signed/stateless cookies — opaque rows make server-side logout and
password-change invalidation trivial (delete rows) and leave no signing
material to manage. Tiers: **session** (sliding, default 24 h) and
**remember-me** (sliding, default 90 d; login-form checkbox), both
configurable. Login regenerates the token (fixation defense); logout deletes
the row; password change deletes all rows except the acting session.
Expired-row pruning rides the existing scheduler. Cookie: HttpOnly,
SameSite=Lax, Path=/, `Secure` conditional on transport with the decision
documented (DEP owns TLS).

### 5. CSRF + WebSocket Origin (FRG-SEC-005)

Cookie surface: SameSite=Lax **plus** an Origin/Referer check on unsafe
methods — reject foreign or absent-Origin state changes under cookie auth; no
token dance for a same-origin SPA. API-key surface CSRF-immune by
construction. WS handshake validates Origin against the deployment's own
origin, allowlist configurable for reverse-proxy setups; cross-origin sockets
refused pre-upgrade.

### 6. Bootstrap and upgrade (the BREAKING change)

Config validation requires `FORAGERR_ADMIN_USER`/`FORAGERR_ADMIN_PASSWORD` —
fail-fast before migrations or data access with the one-line-compose fix
message, exactly the FRG-AUTH-011 keystore precedent (and ordered directly
after that check). First authed boot seeds principal + OPDS credential +
API key; thereafter changed env creds re-seed on boot (audit-visible in logs
as a structured event even before `m8-rate-audit` formalizes the event set)
— the self-lockout recovery path. No unauthenticated window ever exists.
FRG-AUTH-001 retires; RISK-020 Accept → Mitigated; RISK-022/G-5 close; STRIDE
gains session/cookie/CSRF rows. Release notes carry the upgrade block; the
demo deployment gains the two env vars (owner flag rides the existing
:8790 list).

### 7. Frontend: minimal login + 401 interception

One login route in the SPA (username, password, remember-me checkbox,
tokens-compliant styling); the API client intercepts 401 → redirect to login
with return-path; logout control in the existing user/settings surface. M9
polishes visuals. e2e helpers gain an authenticated-session setup step so
existing scenarios keep passing; new negative-path scenarios assert the
refusals.

## Risks / Trade-offs

- [Self-lockout] → env re-seed on boot is the recovery; backoff (not hard
  lockout) arrives in `m8-rate-audit`; documented in the manual.
- [Session table growth] → scheduler prune + sliding expiry bounds rows.
- [Remember-me theft on shared device] → 90 d is a default not a floor;
  configurable; logout-all lands with Settings work in `m8-keys-opds`.
- [Reverse-proxy Origin mismatch breaks WS] → configurable allowlist;
  documented for proxy users.
- [Env creds visible in compose] → same trust class as
  `FORAGERR_SECRET_KEY`; secrets docs gain an "environment trust class"
  section covering all three.
- [Interim window where lifecycle UI is absent] → between v0.7.0 and
  `m8-keys-opds`, key/OPDS rotation is env-reseed-only; acceptable for the
  single-operator deployment, noted in release notes.

## Migration Plan

One migration (next free number at impl): `principal` + `sessions` tables,
credential hash columns. Rollback: downgrade re-opens the unauthenticated
surface — release notes state this explicitly (it is the pre-M8 posture, not
a corruption risk). Deploy order: set env vars → upgrade → first boot seeds →
log in.

## Open Questions

- Exact scrypt parameters — benchmark on target hardware at impl, record
  constants + rationale.
- Whether the bootstrap API-key surfacing lands as a first-login notice here
  or waits entirely for `m8-keys-opds` (decide at impl; either keeps the key
  out of logs).
