# m8-keys-opds

## Why

`m8-auth-core` (v0.7.0) shipped verification for all three credential surfaces
but deliberately deferred their lifecycle: today the API key is visible exactly
once (bootstrap), the OPDS password is changeable only via env re-seed, the
admin password is changeable only via the env recovery path, and — the sharpest
edge — an in-app password change would be **silently reverted on every boot**
by a stale `FORAGERR_ADMIN_PASSWORD`, because re-seed compares the env pair
against the *live* credentials instead of the *last-seeded env pair*. This
change completes the credential lifecycle (FRG-AUTH-005/006/007 flip to
implemented) and folds in the items the core security gate deferred here. It is
the second of three M8 changes; `m8-rate-audit` (FRG-AUTH-009) follows.

## What Changes

- **Settings → Security surface** (SPA + API): the operator manages all three
  credentials from an authenticated session.
- **Admin password change in-app** (FRG-AUTH-004 tail): requires the current
  password, invalidates every *other* session while preserving the acting one
  (re-introduces `invalidate_others`, removed as dead code in core), and emits
  the `auth.password_changed` audit log line.
- **Env re-seed fingerprint** (FRG-AUTH-002 amendment — the deferred footgun
  fix): the boot re-seed decision compares the env pair against a stored
  fingerprint of the pair *as last seeded*, not against the live credentials.
  An in-app password change with a stale env var is now a no-op at boot;
  recovery = set a **new** env pair (differs from the fingerprint), exactly as
  documented. Upgrade backfill: a NULL fingerprint falls back to the core
  semantics once, then records the fingerprint.
- **API key display-once + rotation** (FRG-AUTH-006/007 flip): Settings shows
  the key only immediately after generation/rotation (masked otherwise, never
  re-retrievable); rotation invalidates the old key immediately. The one-shot
  `POST /api/v1/auth/bootstrap-key` handout remains the first-boot path.
- **Independent OPDS password change** (FRG-AUTH-005 flip): own field in
  Settings, requires the *admin* password to authorize, re-prompts only reader
  apps. Closes the "independence only via bootstrap env var" residual noted on
  RISK-003.
- **OPDS Basic verify-cache** (core-gate deferral): a short-TTL, bounded,
  in-process cache over the per-request scrypt verify (OPDS readers send Basic
  on every request), invalidated on any OPDS/admin credential change. Negative
  results are not cached.
- **Logout-all** (FRG-AUTH-004 tail): a Settings control that deletes every
  session row including the acting one (the remember-me-on-a-shared-device
  recovery from the pre-design risk list).

## Capabilities

### New Capabilities

(none — all requirements exist in the `auth` baseline)

### Modified Capabilities

- `auth`: FRG-AUTH-002 (re-seed fingerprint semantics — complete scenario
  restatement), FRG-AUTH-004 (user-initiated password change preserving the
  acting session + logout-all — complete scenario restatement), FRG-AUTH-005
  (Settings change flow + verify-cache invalidation scenarios), FRG-AUTH-007
  (display-once/rotation elaborated from the UI side). FRG-AUTH-006 flips to
  implemented with no delta (implemented exactly as spec'd; its lifecycle half
  lives in 007).

## Impact

- Backend: `auth/` gains credential-lifecycle routes (password change, OPDS
  password change, API-key rotate, logout-all) + `invalidate_others`; bootstrap
  re-seed switches to the fingerprint comparison; OPDS verify-cache in the
  perimeter's Basic path; migration `0024` (fingerprint column(s) on
  `principal`). All new routes are inside the default-deny perimeter (born
  protected; the FRG-AUTH-010 route-inventory test covers them automatically)
  and are unsafe-method session-cookie calls, so the existing FRG-SEC-005
  Origin check applies.
- Frontend: Settings → Security page (current-password confirm, key
  display-once modal, logout-all confirm); no new nav area beyond a Settings
  section.
- e2e: password change (acting session survives, other session dies), key
  rotation (old key 401s immediately), OPDS password change (old Basic creds
  401, new succeed), logout-all, stale-env-boot no-revert.
- Docs: `docs/manual/` (managing credentials in Settings; recovery semantics
  update — env recovery now requires a *new* pair), `docs/security/`
  (risk-register: RISK-003 residual closes; threat-model notes for the
  verify-cache and fingerprint-at-rest — the fingerprint is a scrypt hash,
  same protection class as the password hash it shadows).
- No dependency changes (`soup_check` stays 0; SOUP register untouched).
- Registry: FRG-AUTH-005/006/007 flip `approved → implemented` at merge.
- Version: **v0.8.0** (feature; the re-seed semantics change is behavioral but
  non-breaking — no config change required; release notes call it out).
- Gate: security-touching (credential lifecycle) → tiered-gates standard says
  full fleet + Codex with adversarial angles on the credential-change flows
  (authorization, session preservation, cache invalidation).

## Non-goals

Username change in-app (env re-seed remains the only rename path); multi-key /
scoped API keys (backlog); rate limiting, backoff, and structured audit events
beyond the log lines named here (`m8-rate-audit`); `/health` response trimming
(DEP triage item, not auth); Settings visual polish (M9); TLS (DEP).

## Approval

Covered by the owner's standing grant, 2026-07-12 (session memory
`m8-standing-grant`): run approved development through the M8 auth milestone
without per-change approval; hard stop at M9 UI refinement. Scope follows the
orchestrator decision recorded in the m8-auth-core proposal (lifecycle =
`m8-keys-opds`) plus the core gate's explicitly-deferred items (verify-cache,
env-revert footgun, `invalidate_others` re-add). Design authority remains the
m8-auth pre-design (branch `change/m8-auth`, ded296c); core's design.md wins
where they differ.
