# m8-keys-opds — design

## Context

`m8-auth-core` (v0.7.0) left the credential *verification* paths live on all
three surfaces and a single `principal` row holding `password_hash`,
`opds_password_hash`, and `api_key_sha256`. Lifecycle is env-only: the boot
re-seed in `auth/bootstrap.py` is the sole way to change any credential, and
its comparison — "env password no longer verifies against the live hash" —
becomes actively wrong the moment an in-app change exists (silent revert +
session wipe on every boot with a stale env var). The core gate deferred three
items here by name: the OPDS Basic verify-cache, the env-revert footgun, and
re-adding `invalidate_others` alongside the password-change surface. Design
authority: m8-auth pre-design (ded296c), core's design.md where they differ.

## Goals / Non-Goals

**Goals:** complete the single-principal credential lifecycle from an
authenticated Settings surface; make boot re-seed compare against *what the
env last seeded*, not what the credential currently is; keep OPDS per-request
verification cheap without weakening it.

**Non-Goals:** username change in-app; multi-key or scoped API keys; rate
limiting/backoff and the formal audit-event schema (`m8-rate-audit`); visual
polish (M9); `/health` trimming (DEP).

## Decisions

### 1. Env re-seed fingerprints (the footgun fix)

Two nullable columns on `principal`: `env_password_hash` and
`env_opds_password_hash` — scrypt hashes (same KDF path as the credentials
themselves, so a DB leak exposes nothing weaker) of the env values **as last
seeded**. Boot logic becomes per-credential and symmetric:

- **Admin pair**: re-seed iff the pair is present AND (username differs from
  the principal's, or the env password fails to verify against
  `env_password_hash`). Re-seed updates both the live hash and the
  fingerprint, and invalidates all sessions (unchanged recovery semantics).
- **OPDS**: re-seed iff `FORAGERR_OPDS_PASSWORD` is set AND fails to verify
  against `env_opds_password_hash` — now *decoupled* from the admin re-seed
  (today OPDS recovery requires tripping the admin path; after this, setting a
  new OPDS env value alone recovers it, and an admin re-seed no longer
  clobbers an in-app OPDS password from a stale env var). OPDS re-seed
  invalidates the verify-cache, not sessions.

Consequences, documented in the manual: an in-app change with stale env vars
is a boot no-op (the fix); recovery requires a **new** env value (one that
differs from the last-seeded one), not re-asserting an old one.

**Backfill**: post-upgrade the fingerprints are NULL. A NULL fingerprint can
only exist before any in-app change was possible, so the boot hook falls back
to the core comparison (verify env value against the *live* hash) exactly
once, then records the fingerprint — no migration-time KDF work, no behavior
change on the upgrade boot itself.

*Alternative considered*: an explicit `FORAGERR_RESET_ADMIN=1` opt-in flag —
rejected: adds an env knob that must be remembered *and removed after use*
(its own footgun), whereas the fingerprint preserves the documented
"changed pair = recovery" contract verbatim.

### 2. Credential-lifecycle endpoints (session surface, re-auth required)

All new routes live under `/api/v1/auth/`, inside the default-deny perimeter
(born protected; the FRG-AUTH-010 route-inventory test picks them up
automatically) and Origin-checked by the existing FRG-SEC-005 dependency:

| Route | Action |
|---|---|
| `POST /api/v1/auth/password` | change admin password; body carries `current_password` + `new_password` |
| `POST /api/v1/auth/opds-password` | set OPDS password; body carries `current_password` (the **admin** password) + `new_password` |
| `POST /api/v1/auth/api-key/rotate` | rotate; body carries `current_password`; response carries the raw key exactly once |
| `POST /api/v1/auth/logout-all` | delete every session row including the acting one |
| `GET /api/v1/auth/credentials` | non-secret status for the Settings page (username, key rotated-at, OPDS-differs-from-admin flag) |

**Uniform re-auth rule**: every credential *write* requires the current admin
password in the request body — a stolen/ridden session alone cannot mint a
durable credential (API key) or lock the operator out (password change).
Logout-all deliberately requires no password: it grants nothing (pure session
destruction) and is the shared-device recovery, where friction is the enemy.
Failed re-auth returns the same generic 403 regardless of which field was
wrong, and these failures are structured-logged (they feed `m8-rate-audit`'s
counters later).

**Session semantics**: admin password change calls `invalidate_others`
(re-introduced in `auth/sessions.py`: delete all rows for the principal except
the acting session's) — AUTH-004's spec'd acting-session preservation. Env
re-seed keeps `invalidate_all`. API-key rotation and OPDS change touch no
sessions.

### 3. API key display-once

The raw key exists outside the DB in exactly two moments: the bootstrap
one-shot (`POST /api/v1/auth/bootstrap-key`, unchanged) and the rotate
response. Settings shows only rotated-at metadata from `GET /credentials` —
no last-N hint is stored or shown (storing a hint weakens the "SHA-256 only at
rest" property for marginal UX on a single-key system). The SPA renders the
rotate response in a display-once modal with copy-to-clipboard and an explicit
"you won't see this again" note, and never persists it.

### 4. OPDS Basic verify-cache

OPDS readers send Basic on every request, which currently costs a full scrypt
verify (~100–250 ms, off-loop but still burned CPU per catalog/page hit). Add
a small in-process cache in the perimeter's Basic path: key =
SHA-256(username + NUL + password) of the *presented* credentials, value =
verified-OK, TTL 60 s, capacity 8 entries with drop-oldest (one reader is the
realistic population; the cap only bounds abuse). **Positive results only** —
a failed verify is never cached (no negative-cache DoS where a garbage
password pins the real one out, and no stale-deny after a password change).
Invalidation: any principal-row credential write (in-app OPDS/admin change,
env re-seed) clears the cache. Plaintext is never stored; a cache-key preimage
is the credential itself, and SHA-256 of a high-entropy random token is the
same protection class core already accepted for the API key — for a
low-entropy password the TTL+clear-on-change bounds exposure to process
memory, same class as the request itself.

### 5. Settings → Security page

One new Settings section (React, tokens-compliant, M9 polishes): four cards —
web password change, OPDS password change (with "used by reader apps" copy),
API key (rotated-at + rotate button + display-once modal), and sessions
(logout-all with confirm). Current-password fields are `type=password`,
autocomplete-off, cleared on success. 401/403 mapping rides the existing
`mapApiError` machinery; logout-all lands the SPA back on the login screen via
the existing 401 interceptor.

## Risks / Trade-offs

- [Fingerprint columns misread as credential material] → they are scrypt
  hashes of *env* values, same protection class as the live hashes beside
  them; threat-model note added.
- [Verify-cache extends a revoked OPDS password ≤60 s] → in-app changes clear
  the cache synchronously; only an *external* change vector (direct DB edit)
  could see the TTL window — out of threat model (DB write = game over).
- [Rotate response lost (browser crash before copy)] → rotate again; the
  operation is cheap and idempotent in effect.
- [Logout-all without password enables session-riding nuisance] → accepted:
  destroys, grants nothing; the rider already held the session.
- [Re-asserting an *old* env password no longer recovers] → documented in
  manual + release notes: recovery = set a value that differs from the last
  env-seeded one.

## Migration Plan

Migration **0024**: `ALTER TABLE principal ADD COLUMN env_password_hash TEXT
NULL` + `env_opds_password_hash TEXT NULL`. No data backfill (NULL triggers
the one-time boot fallback, Decision 1). Rollback: columns are additive;
downgrading the app ignores them (core's comparison resumes — the footgun
returns, which is the pre-change posture, not corruption). Version v0.8.0,
CHANGELOG + release notes carry the re-seed-semantics note.

## Open Questions

(none — parameters above are decided; e2e negative paths follow the UAT
negative-paths rule as usual)
