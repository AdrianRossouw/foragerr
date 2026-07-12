# m8-rate-audit

## Why

`m8-auth-core` (v0.7.0) and `m8-keys-opds` (v0.8.0) shipped the perimeter and
the credential lifecycle, but failed authentication is still free: an attacker
(or a misbehaving reader app) can hammer the login form, the OPDS Basic realm,
or the API-key header at line rate, and the only audit trail is a scattering of
ad-hoc log lines (`auth.reauth_failed`, `auth.password_changed`, …) added
piecemeal by the earlier changes. FRG-AUTH-009 — the last approved M8
requirement — closes both gaps: throttle failed authentication and make every
authentication-relevant event a uniform, structured, credential-free audit
event. This is the third and final M8 change.

## What Changes

- **Failure rate limiting with backoff, not lockout**: in-process
  sliding-window counters over failed authentication attempts, keyed per
  (client IP, surface) and per principal, across all three surfaces (login
  form, OPDS Basic, API key). After N failures in the window (default 5 per
  15 minutes) further attempts on that key are answered with an exponentially
  growing delay/refusal (429 with `Retry-After` where the surface allows it).
  Explicitly **no hard lockout** — the operator locking themselves out of a
  single-user tool is the bigger risk (pre-design §6); env re-seed remains the
  recovery of last resort. A successful authentication resets the counters for
  that key.
- **Uniform structured audit events**: one event vocabulary
  (`auth.login.success`, `auth.login.failure`, `auth.logout`,
  `auth.password_changed`, `auth.opds_password_changed`, `auth.opds_failure`,
  `auth.apikey_failure`, `auth.apikey_rotated`, `auth.reauth_failed`,
  `auth.backoff_triggered`, `auth.reseed`) carrying source IP and surface,
  never credential material and never unsanitized client-controlled strings
  (log-injection hardening on the submitted username). The existing ad-hoc
  lines from core/keys-opds are migrated into this vocabulary.
- **Visibility in System → Logs**: audit events flow through the standard
  logging pipeline, so the existing logs viewer shows them with no frontend
  work beyond verifying filterability by the `foragerr.auth` logger.

## Capabilities

### New Capabilities

(none — FRG-AUTH-009 exists in the `auth` baseline, registered `approved`)

### Modified Capabilities

- `auth`: FRG-AUTH-009 — the placeholder "Baseline acceptance" scenario is
  replaced with the complete concrete scenario set (backoff after N failures
  per key; per-key isolation; counter reset on success; no hard lockout —
  correct credentials still work after the window passes; audit events for
  every success/failure/lifecycle action with source IP + surface and no
  credential material; log-injection-hostile username handling). Complete
  scenario restatement per the MODIFIED-delta lesson.

## Impact

- Backend only: a small `auth/ratelimit.py` (sliding-window counters +
  backoff policy, in-process, no persistence — counters reset on restart,
  which is acceptable for the threat model and avoids a migration) wired
  into the login route and the perimeter's Basic/API-key failure paths; an
  `auth/audit.py` (or equivalent) event helper unifying the existing log
  lines. No new endpoints, no migration, no frontend changes.
- e2e: scripted bad-login burst → throttled per policy + `auth.backoff_triggered`
  in captured logs; correct login after backoff window → succeeds (no
  lockout); negative check that no password/key material appears in logs.
- Docs: `docs/manual/admin/authentication.md` (rate-limit behavior, what the
  operator sees, tuning knobs if any); `docs/security/` in the same change
  per FRG-PROC-006 — threat-model note (brute-force mitigation, the
  client-IP-keying trust boundary: direct-connection IP only, no
  X-Forwarded-For trust without explicit proxy config; log-injection
  hardening) and risk-register touch (brute-force residual on RISK-020's
  successor posture).
- No dependency changes (`soup_check` stays 0; stdlib + existing FastAPI
  machinery only).
- Registry: FRG-AUTH-009 flips `approved → implemented` at merge. No new IDs.
- Version: **v0.9.0** (feature — new operator-visible throttling behavior).
- Gate: security-touching but small and surface-neutral (no new endpoint, no
  parser of new untrusted input beyond the already-parsed credentials):
  small-to-medium fleet + Codex **with a dedicated adversarial angle** on
  bypass and abuse (per-key isolation vs. IP spoofing, backoff arithmetic,
  self-lockout/DoS of the legitimate operator, log injection, credential
  leakage into logs) and a tested abuse scenario, per the tiered-gates
  standard for small changes touching security surfaces.

## Non-goals

Persistent/banning rate limits or fail2ban-style IP blocking (backoff only);
rate limiting of authenticated traffic (this is failed-auth only — API
throttling is a different concern); audit-event persistence beyond the
standard log pipeline (no audit table; System → Logs is the viewer); trusting
`X-Forwarded-For` (no reverse proxy in the deployment model; revisit with
DEP's TLS story); frontend surfaces (M9); `/health` trimming (DEP triage).

## Approval

Covered by the owner's standing grant, 2026-07-12 (session memory
`m8-standing-grant`): run approved development through the M8 auth milestone
without per-change approval; hard stop at M9 UI refinement. Scope follows the
orchestrator decision recorded in the m8-auth-core proposal (`m8-rate-audit` =
FRG-AUTH-009, kept as its own change when sized at kickoff). Design authority
remains the m8-auth pre-design (branch `change/m8-auth`, ded296c §6 —
backoff-not-lockout, event vocabulary, counters reset on success).
