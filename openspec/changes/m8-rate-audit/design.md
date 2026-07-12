# m8-rate-audit — design

## Context

The perimeter (`auth/perimeter.py::_authenticate`) resolves three credential
kinds — session cookie, `X-Api-Key`, OPDS Basic — and the login route
(`auth/routes.py::login`) is the fourth place credentials are checked. Every
failed check today is free and unthrottled; each Basic/login failure burns a
full scrypt verification (deliberately, for timing uniformity), so a failure
flood is also a CPU-exhaustion vector. Audit logging exists only as ad-hoc
lines added by core/keys-opds (`auth.reauth_failed`, `auth.password_changed`,
`auth.opds_password_changed`, `auth.apikey_rotated`) on the
`foragerr.auth` logger. Design authority: m8-auth pre-design (ded296c) §6.

## Goals / Non-Goals

**Goals:**

- Throttle *failed* authentication on all credential-bearing paths with
  escalating temporary refusal; never hard-lock the operator out.
- One structured, credential-free audit vocabulary for every
  authentication-relevant event, visible in System → Logs.
- Shield the scrypt verify paths from failure-flood CPU burn (the limiter
  check runs *before* the KDF).

**Non-Goals:** persistence of counters or audit rows (log pipeline only);
banning/fail2ban semantics; throttling authenticated traffic; trusting
`X-Forwarded-For`; any frontend work.

## Decisions

### 1. What counts as a failure

Only **credential-bearing** failures increment counters: a login POST with
wrong username/password, a present-but-wrong `X-Api-Key`, a
present-but-wrong Basic header. Requests with *no* credential (bare OPDS
probe answered with the realm challenge, expired/absent session cookie) never
count — an expired remember-me cookie retrying on every SPA call is normal
traffic, not guessing, and counting it would back off the legitimate
operator. Cookie-auth failures are therefore exempt by design.

### 2. Keying and enforcement

Two sliding-window counter families in one in-process registry:

- **(client IP, surface)** — the enforcing counter. Surface ∈
  {`login`, `api_key`, `basic`}. After N failures (default 5) within the
  window (default 15 min), further attempts from that key are refused
  **before any KDF work** with 429 + `Retry-After`, the refusal deadline
  growing exponentially (base 30 s, doubling per excess failure, capped at
  the window length). Correct credentials after the deadline succeed — a
  temporary per-key refusal, never a lockout.
- **(surface,) global** — an observability counter (single principal, so
  per-principal ≡ global-per-surface). It never blocks (an attacker must not
  be able to lock the operator out by spraying failures from many spoofed
  sources); crossing its threshold emits `auth.backoff_triggered` so a
  distributed pattern is visible in the audit trail even when no single IP
  trips enforcement.

Client IP = `request.client.host` (direct connection only). No
`X-Forwarded-For` parsing — the deployment model is direct uvicorn on a
tailnet; this trust boundary goes in the threat model, revisited with DEP's
TLS/proxy story.

A success resets the counters for its (IP, surface) key.

### 3. Counter mechanics

`auth/ratelimit.py`: per-key deque of monotonic timestamps, pruned on
access; registry is a dict capped at 1024 distinct keys with
oldest-idle eviction (bounded memory even under source spraying — mirrors
the verify-cache's bounded-size discipline). `time.monotonic()` throughout
(immune to wall-clock jumps). Counters are process-local and reset on
restart — acceptable for the threat model (restart frequency ≪ window) and
avoids a migration; documented in the manual.

### 4. Enforcement points

- `login` route: limiter check at the top (before the constant-work KDF);
  failure increments, success resets.
- `_authenticate` step 2 (API key): increment when a *present* key mismatches;
  the limiter check wraps the lookup. 429 propagates from the perimeter.
- `_authenticate` step 3 (Basic): limiter check after `_decode_basic`
  succeeds and before cache/KDF; increment on verify failure. The 429 (not
  the realm challenge) is returned for a throttled key so readers surface the
  error rather than re-prompting in a loop.

429 refusal (no tarpit `asyncio.sleep`): holding connections open to delay is
itself a connection-exhaustion vector; an immediate refusal with
`Retry-After` gives the same guessing economics without tying up the loop.
The spec's "backoff or temporary lockout" language covers this shape.

### 5. Audit vocabulary

`auth/audit.py` — one helper, `audit_event(event, request, surface, **fields)`,
writing to the existing `foragerr.auth` logger in a fixed
`<event> key=value …` shape so System → Logs shows and filters them with no
frontend change. Vocabulary (migrating the four existing ad-hoc lines into
the same shape): `auth.login.success`, `auth.login.failure`, `auth.logout`,
`auth.password_changed`, `auth.opds_password_changed`, `auth.opds_failure`,
`auth.apikey_failure`, `auth.apikey_rotated`, `auth.reauth_failed`,
`auth.backoff_triggered`, `auth.reseed` (bootstrap already logs the re-seed;
it adopts the shape). Fields: `surface`, `ip`, plus event-specifics — never
password/key material, never raw client strings: the submitted username is
the one attacker-controlled string that appears, and it is
control-character-stripped and length-capped before logging (log-injection
hardening; newline/ANSI injection gets a dedicated test).

OPDS Basic **successes** are logged per *verification* (cache fill), not per
request — a reader sends Basic on every request and per-request success
events would drown the log; one event per TTL window per reader preserves
the "successes are logged" requirement without the spam.

### 6. Testing

Unit: window arithmetic, exponential deadline growth + cap, key isolation,
success-reset, registry eviction bound. Route/perimeter: per-surface 429
behavior incl. KDF-not-run-when-throttled (assert via call counting),
throttled-then-correct-credentials-succeeds-after-deadline, cookie-failure
exemption. Audit: every event fires where specified; log-injection; negative
scan that no credential material reaches any handler's records. e2e: scripted
bad-login burst → 429 + `auth.backoff_triggered` visible; recovery after
deadline. All tagged FRG-AUTH-009.

## Risks / Trade-offs

- [Operator self-DoS via shared IP (e.g. same tailnet host as an attacker or
  a misconfigured reader hammering Basic)] → enforcement is per-(IP, surface):
  a looping reader throttles only `basic` from that host; login from the
  operator's browser is a different (IP, surface) key in the common case, and
  the refusal is temporary regardless. Env re-seed remains last-resort.
- [Global counter as lockout vector] → global counter observes and logs but
  never blocks, by decision 2.
- [Memory growth under IP spraying] → capped registry (1024 keys,
  oldest-idle eviction). Eviction under active attack degrades enforcement
  granularity, not correctness, and the global counter still fires.
- [Counters lost on restart] → accepted; restart cadence ≪ window and the
  audit trail records the pre-restart burst.
- [429 on OPDS confusing readers] → manual documents the reader-visible
  behavior; deadline cap keeps the worst wait at the window length.

## Migration Plan

No migration, no config surface changes (thresholds are module constants
with settings overrides only if the implementation finds them already
plumbed — no new required env). Rollback = revert the merge.
