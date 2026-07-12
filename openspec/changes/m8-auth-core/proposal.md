# m8-auth-core

## Why

M8 is the milestone the 1.0 cut names as the hard gate for "safe for strangers
to deploy": RISK-020's no-auth acceptance (Tailscale-only exposure as the
compensating control) ends here. This change is the invariant-bearing core of
the milestone — the default-deny perimeter, login, and sessions — implementing
the m8-auth pre-design (design authority on branch `change/m8-auth`, commit
ded296c; owner decisions captured 2026-07-11/12). Two follow-up changes
(`m8-keys-opds` credential lifecycle, `m8-rate-audit` throttling + audit)
complete the milestone.

## What Changes

- **Default-deny auth perimeter over every surface** (FRG-AUTH-010): one auth
  dependency installed at the application root covering UI, API, OPDS, and the
  WebSocket; the exempt list is fixed at exactly `/health` + the login route
  and its static assets. Proven three ways: by construction (dependency above
  all routers), by an exhaustive route-inventory test over `app.routes`, and
  by e2e negative paths per surface.
- **Mandatory single-user form login + sessions** (FRG-AUTH-002/004): no
  auth-mode-none, no escape hatch (owner decision). DB-backed opaque-token
  sessions, two sliding tiers — session (default 24 h) and remember-me
  (default 90 d) — HttpOnly SameSite=Lax cookie, token regeneration on login
  (fixation defense), server-side logout, password-change invalidation of all
  other sessions, scheduler-pruned expiry.
- **scrypt password hashing** (FRG-AUTH-003, **amendment**): "argon2id or
  bcrypt" → memory-hard modern KDF (scrypt from the already-SOUP'd
  `cryptography` dependency, per-credential salts) — owner decision; zero new
  dependencies for the milestone.
- **Env bootstrap, no unauthenticated window** (**BREAKING**): first boot of
  this release fails fast without `FORAGERR_ADMIN_USER`/`FORAGERR_ADMIN_PASSWORD`
  (keystore precedent, actionable error), then seeds the principal, the OPDS
  credential (from `FORAGERR_OPDS_PASSWORD` or equal to the admin password),
  and a generated API key. Changed env creds re-seed on boot (the recovery
  path). Release notes carry the upgrade block.
- **Credential verification for all three surfaces ships here** so the
  perimeter is coherent on day one: session cookie (UI), `X-Api-Key` header
  check (programmatic API, header-only — no query param), OPDS HTTP Basic in
  its own realm. Lifecycle — key display/rotation, OPDS password change in
  Settings — is deferred to `m8-keys-opds` (FRG-AUTH-005/006/007 flip there,
  not here).
- **CSRF stance + WebSocket Origin validation** (FRG-SEC-005): SameSite=Lax
  plus Origin/Referer check on unsafe methods under cookie auth; API-key
  surface CSRF-immune by construction; WS handshake validates Origin against a
  configurable allowlist and runs the same auth dependency, refusing
  pre-upgrade.
- **Minimal login screen + 401 handling in the SPA** (tokens-compliant; M9
  polishes the visual design).
- **FRG-AUTH-001 retires**: the no-auth accepted risk ends; its scenarios
  invert into perimeter negative tests. RISK-020 flips Accept → Mitigated;
  RISK-022/G-5 close; STRIDE gains session/cookie/CSRF rows (FRG-PROC-006, in
  this change).
- One migration: principal + sessions tables (+ credential hash columns).

## Capabilities

### New Capabilities

(none — all requirements exist in the `auth` and `sec` baselines)

### Modified Capabilities

- `auth`: FRG-AUTH-002 (mandatory login, scenario elaboration), FRG-AUTH-003
  (KDF amendment to scrypt), FRG-AUTH-004 (two-tier sliding sessions, full
  scenario set), FRG-AUTH-010 (exempt list pinned, three-way proof),
  FRG-AUTH-001 (retired — superseded by the perimeter; scenarios invert).
- `sec`: FRG-SEC-005 (CSRF stance + WS Origin allowlist, scenario
  elaboration).

## Impact

- Backend: new `auth/` package (perimeter dependency, principal/session
  models + repo, scrypt hashing, bootstrap seeding, login/logout routes);
  app factory installs the root dependency; WS handshake auth + Origin check;
  migration `00xx_auth_principal_sessions`; config gains admin/OPDS bootstrap
  env vars + session/remember-me timeout + WS origin allowlist settings.
- Frontend: login screen, 401-redirect interceptor in the API client, logout
  control.
- e2e: negative paths per surface (unauthenticated UI/API/OPDS/WS refused),
  login + remember-me flows; existing scenarios gain an authenticated setup
  step.
- Docs: `docs/manual/` (login, remember-me, env bootstrap, upgrade/BREAKING
  block), README auth-posture labelling if touched, `docs/security/`
  threat-model STRIDE rows + risk-register flips (RISK-020 Mitigated,
  RISK-022 closed), secrets docs gain the environment-trust-class section.
- No dependency changes (`cryptography` already SOUP'd; `soup_check` stays 0).
- Registry: FRG-AUTH-002/003/004/010 + FRG-SEC-005 flip `approved →
  implemented` at merge; FRG-AUTH-001 `implemented → retired`.
- Version: **v0.7.0** (BREAKING bootstrap requirement; CHANGELOG + pyproject
  bump in-change per FRG-PROC-013).
- Gate: security-touching (new listener surface behavior, credentials) → full
  eight-angle fleet + Codex, adversarial angles on the perimeter and session
  handling (tiered-gates standard).

## Non-goals

Multi-user/roles, OIDC/reverse-proxy auth, TOTP/2FA, scoped API keys (all
backlog); TLS termination (DEP's story — `Secure` cookie flag conditional and
documented); API-key rotation UI and OPDS password change (`m8-keys-opds`);
login rate limiting, lockout backoff, and structured auth audit events
(`m8-rate-audit`); login-screen visual polish (M9).

## Approval

Covered by the owner's standing grant, 2026-07-12 (session memory
`m8-standing-grant`): run approved development through the M8 auth milestone
without per-change approval; hard stop at M9 UI refinement. The design
decisions implemented here are the owner decisions recorded in the m8-auth
pre-design (2026-07-11/12, branch `change/m8-auth`, commit ded296c):
mandatory login with remember-me comfort, env bootstrap credentials, scrypt
as the FRG-AUTH-003 amendment, default-deny perimeter with the three-way
FRG-AUTH-010 proof.
