# m8-rate-audit-followups

## Why

The v0.9.0 (`m8-rate-audit`, FRG-AUTH-009) release passed its gate, but a
post-release backstop review at the **full eight-angle fleet + Codex** — run
after the change had already merged, because the gate had been under-provisioned
for a credential surface — surfaced one confirmed medium-severity bug plus a
cluster of low-severity hardening and cleanup items. This change lands the fixes
as a patch release. It changes **no enforcement behavior**; it clarifies
FRG-AUTH-009 to spell out two properties the bug revealed were under-specified
(the login UI must surface a 429 as wait-not-retry; the audit helper must be
exception-safe), and hardens the implementation to match.

## What Changes

- **Login form now handles HTTP 429** (the confirmed bug): `LoginScreen`
  special-cased only 401 and dropped 429 into a generic "Could not sign in.
  Try again." — which *contradicts* the admin manual's documented guidance
  (a throttled operator is told to wait, not retry) and discards the
  `Retry-After` the backend supplies. It now shows a throttle-specific message
  surfacing the wait, with a regression test.
- **`audit_event` can never break the audited request** (structural hardening):
  the "must never raise" property held only by construction across all current
  call sites; it is now wrapped in a swallow-all guard so a future caller
  passing an object with a raising `__str__` can't take down the auth path.
- **Global observation counter is bounded by a size cap**, not just the time
  window (was O(failures-in-window); now O(threshold)), and empty per-key
  deques are reclaimed immediately in `retry_after`.
- **Mechanical dedup**: the `client_ip` helper (copied three times) collapses to
  one exported helper; the login route reuses the perimeter's throttle-raise
  helper instead of hand-rolling a second `HTTPException(429)` (and drops its
  now-unneeded `import math`).
- **Doc note**: the `request.client is None` shared-bucket case is recorded
  alongside the existing S1 (docker-IP-collapse) caveat in the threat model.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `auth`: FRG-AUTH-009 — the requirement is clarified (complete scenario
  restatement) to make explicit two properties the v0.9.0 bug revealed were
  under-specified: the login UI SHALL surface a 429 as a distinct
  wait-not-retry message, and the audit helper SHALL be exception-safe (a
  failed render never propagates into the audited request). No enforcement
  behavior changes; two new scenarios pin the fixes.

## Impact

- Frontend: `LoginScreen.tsx` (429 branch) + `LoginScreen.test.tsx` (429 case).
- Backend: `auth/audit.py` (try/except guard + exported `client_ip`),
  `auth/ratelimit.py` (global-deque cap, empty-deque reclaim),
  `auth/perimeter.py` + `auth/routes.py` (use the shared `client_ip` and
  throttle-raise helpers). Behavior-preserving refactors verified by the
  existing FRG-AUTH-009 unit + enforcement + e2e suites.
- Docs: `docs/security/threat-model.md` (one-line `client is None` note).
- No migration, no dependency change (`soup_check` stays 0), no new endpoint,
  no new attack surface.
- Registry: no row changes (no new IDs; FRG-AUTH-009 already implemented).
- Version: **v0.9.1** (patch — bugfix + hardening, no behavior change beyond
  the login-form message).
- Gate: the underlying v0.9.0 code was just reviewed by the full eight-angle
  fleet + Codex; this delta gets a focused security/correctness pass on the
  changed lines + Codex, with the login-429 abuse/UX path and the
  refactor-is-behavior-preserving property as the explicit checks.

## Non-goals

The larger `audit_event` → `KeyValueFormatter`/`extra=` consolidation
(simplification finding #3 — a real refactor that moves fields out of the log
message and touches every audit assertion) is deferred to its own change. The
failure-tail triplication and the global-counter threshold/event-distinctness
tweak (findings #2-tail, #4) are likewise left as advisory follow-ups rather
than risked in a patch. Backend audit persistence remains the queued
post-M8 durable-audit-store follow-up.

## Approval

Bugfix/hardening to the shipped M8 release — covered by the owner's standing
grant, 2026-07-12 (`m8-standing-grant`: "bugfixes need NO approval"), and the
owner's explicit 2026-07-12 decision to ship these backstop findings as a
focused v0.9.1. Still inside M8 (patching the M8 release), before the M9
UI-refinement hard stop.
