# AUTH — Authentication Specification

## Purpose

Baseline requirements for authentication, mined from the
Phase 1 reference research (`docs/research/`). Baseline depth per the Phase 2 scope
decision: SHALL + coarse acceptance; scenario-level elaboration happens in the
milestone change that implements each requirement (FRG-PROC-003, FRG-PROC-009).
## Requirements

### Requirement: FRG-AUTH-002 — single-user web login

The system SHALL protect the web UI and API with a single-user username/password login (form-based session auth for the UI), with no anonymous access to any non-exempt endpoint. Login SHALL be mandatory — no auth-mode-none or other bypass configuration exists (owner decision 2026-07-11/12). The single principal SHALL be seeded from `FORAGERR_ADMIN_USER`/`FORAGERR_ADMIN_PASSWORD` at first authed boot; startup SHALL fail fast with an actionable error when they are absent and no principal exists. At each later boot the system SHALL compare the env pair against a stored fingerprint of the pair *as last seeded* (a KDF hash, never plaintext) and SHALL re-seed the principal only when the env pair is present and differs from that fingerprint (the lockout-recovery path) — an env pair that merely differs from the *live* credentials (because the operator changed the password in-app) SHALL NOT trigger a re-seed. No unauthenticated setup window SHALL exist at any point.

- **Milestone**: M8
- **Source**: mylar-feature-surface.md §8 AUTH ("forms+session login with timeout"); sonarr-architecture.md §7.2 (auth); m8-auth pre-design owner decisions (mandatory, env bootstrap), 2026-07-11/12; m8-auth-core gate deferral (env-revert footgun), 2026-07-12.
- **Notes**: Single-user by design (single-operator tool) — no user table beyond one principal, no roles. Exempt endpoints: health (DEP), login route + its static assets; OPDS has its own realm (FRG-AUTH-005). **BREAKING** at upgrade (shipped in m8-auth-core): the release refuses first boot without the bootstrap env pair, mirroring the FRG-AUTH-011 keystore precedent. Recovery after this change means setting an env value that differs from the last env-seeded one — re-asserting a previously seeded value is a no-op (documented in the manual). A NULL fingerprint (upgrade from v0.7.0) falls back to live-credential comparison exactly once, then records the fingerprint.

#### Scenario: Unauthenticated UI and API access is refused

- **WHEN** a browser or HTTP client requests any non-exempt UI or API route with no session cookie and no API key
- **THEN** API routes return 401 with no resource content, and the SPA redirects the user to the login screen with a return path back to the originally requested view

#### Scenario: Correct credentials establish a session; wrong ones do not

- **WHEN** the login form is submitted with the seeded principal's correct username and password, and separately with an incorrect password or unknown username
- **THEN** the correct submission establishes an authenticated session and lands on the return path, while each incorrect submission yields the same generic failure (no username/password distinction) and establishes no session

#### Scenario: Missing bootstrap credentials block first boot

- **WHEN** the first release containing mandatory auth boots with no existing principal and `FORAGERR_ADMIN_USER`/`FORAGERR_ADMIN_PASSWORD` absent or empty
- **THEN** the process exits non-zero during configuration validation, before migrations or serving any request, with an error naming both variables and showing how to set them — and at no point does the application serve any surface unauthenticated

#### Scenario: Changed env credentials re-seed the principal

- **WHEN** the deployment boots with a `FORAGERR_ADMIN_USER`/`FORAGERR_ADMIN_PASSWORD` pair that differs from the fingerprint of the pair as last seeded
- **THEN** the principal is re-seeded to the env values at boot (recovering a lost-password lockout), the fingerprint is updated, the re-seed is logged as a structured event without credential material, and existing sessions for the old credentials are invalidated

#### Scenario: Stale env credentials do not revert an in-app password change

- **WHEN** the operator changes the admin password in Settings and the deployment later reboots with `FORAGERR_ADMIN_PASSWORD` still set to the previously seeded value
- **THEN** the boot is an idempotent no-op — the in-app password remains in force, no sessions are invalidated, and no re-seed event is logged

#### Scenario: Upgrade boot with a NULL fingerprint

- **WHEN** the first boot after upgrading from a release without fingerprint columns runs with the env pair unchanged from what it last seeded
- **THEN** the boot compares the env pair against the live credentials exactly once (no re-seed when they match), records the fingerprint, and all subsequent boots use the fingerprint comparison

### Requirement: FRG-AUTH-003 — password storage with modern KDF

The system SHALL store the user password only as a salted hash using a memory-hard modern password KDF (scrypt via the `cryptography` dependency, with a unique random salt per credential and parameters sized to password-grade verification cost), never reversibly, and SHALL NOT log or echo it. Verification SHALL use constant-time comparison.

- **Milestone**: M8
- **Source**: mylar-feature-surface.md §7/§8 (Mylar stores passwords "optionally obfuscated" — salted-base64) — explicit divergence to real hashing. Amended by m8-auth-core (owner decision 2026-07-11/12): "argon2id or bcrypt" → memory-hard modern KDF (scrypt), reusing the already-SOUP'd `cryptography` primitive — zero new dependencies.
- **Notes**: One of the two "better than Mylar's obfuscation" commitments (the other is at-rest secret encryption, FRG-AUTH-008 — different mechanism: hashing for verification-only credentials, encryption for secrets that must be replayed outbound). scrypt parameters use a costlier profile than the keystore's interactive derivation; constants recorded in code with rationale. Bootstrap env credential values are redaction-registered (FRG-NFR-008) for the process lifetime.

#### Scenario: Only KDF hashes at rest

- **WHEN** the database and configuration files are inspected after bootstrap seeding and after a password change
- **THEN** every stored credential (web password, OPDS password) appears only as a scrypt hash with its per-credential salt — no plaintext, no reversible encoding, and no shared salt between credentials

#### Scenario: Verify path accepts correct and rejects wrong passwords

- **WHEN** the stored hash is verified against the correct password and against candidate wrong passwords
- **THEN** only the correct password verifies, comparison is constant-time, and a tampered or truncated stored hash fails verification rather than erroring into acceptance

#### Scenario: No credential material in logs

- **WHEN** logs are captured across bootstrap seeding, successful login, failed login, and password re-seed
- **THEN** no password, hash, or salt value appears in any log line (bootstrap env values are redaction-registered), and auth log events carry no credential material


### Requirement: FRG-AUTH-004 — session management

The system SHALL issue authenticated sessions as DB-backed opaque tokens delivered in HttpOnly, SameSite cookies, storing server-side only a hash of the token, with two sliding-expiry tiers — a standard session (configurable inactivity timeout, default 24 h) and an opt-in remember-me tier (configurable, default 90 d) selected on the login form. The system SHALL regenerate the session token at login, support explicit logout invalidating the session server-side, and prune expired sessions on the existing scheduler. When account credentials change, the system SHALL invalidate sessions as follows: an env re-seed at boot invalidates every session; a user-initiated password change from Settings invalidates every session *except* the acting one; and a logout-all control SHALL delete every session including the acting one.

- **Milestone**: M8
- **Source**: mylar-feature-surface.md §8 AUTH ("session login with timeout"); m8-auth pre-design owner decision (remember-me comfort tier + logout-all as the shared-device recovery), 2026-07-11/12.
- **Notes**: Opaque DB tokens (not signed cookies) make server-side logout and password-change invalidation row deletes and leave no signing material to manage. `Secure` cookie flag is conditional on transport (Tailscale HTTPS story is DEP's); document the decision. CSRF posture lives in FRG-SEC-005. Logout-all requires no password re-auth (it grants nothing — pure session destruction — and is the shared-device recovery path); credential writes do require re-auth (see FRG-AUTH-005/007 and the change design).

#### Scenario: Cookie attributes and server-side storage

- **WHEN** a session is established and the cookie and database row are inspected
- **THEN** the cookie is HttpOnly and SameSite=Lax with the raw 256-bit token only in the cookie, and the database stores only the token's SHA-256 hash with principal, tier, created/last-seen, and expiry

#### Scenario: Sliding expiry per tier

- **WHEN** a standard session sits idle past its inactivity timeout, and a remember-me session is used within its window
- **THEN** the idle standard session requires re-login, while the active remember-me session slides its expiry forward and stays valid up to its configured tier window

#### Scenario: Login regenerates, logout revokes server-side

- **WHEN** a user logs in (with any pre-existing session cookie present) and later logs out, then replays the old cookies
- **THEN** login issues a fresh token (the prior token no longer authenticates — fixation defense), and after logout the deleted session's cookie yields 401 on replay (back-button included)

#### Scenario: Credential re-seed invalidates all sessions

- **WHEN** the account credentials are re-seeded at boot from a changed env pair while sessions (including remember-me) exist
- **THEN** every session row is deleted — subsequent requests on them return 401 — and access requires a fresh login with the new credentials

#### Scenario: User-initiated password change preserves the acting session

- **WHEN** the operator changes the admin password from Settings (supplying the current password) while other sessions — including a remember-me session on another device — exist
- **THEN** every other session row is deleted and returns 401 on next use, while the acting session continues uninterrupted, and the change is logged as a structured event without credential material

#### Scenario: Logout-all destroys every session

- **WHEN** the operator invokes the logout-all control from Settings
- **THEN** every session row for the principal is deleted, including the acting session's — the SPA lands back on the login screen and every other device requires a fresh login

#### Scenario: Expired rows are pruned

- **WHEN** sessions pass their expiry and the scheduler's prune job runs
- **THEN** expired rows are removed from the sessions table and the table does not grow without bound

### Requirement: FRG-AUTH-005 — HTTP Basic for OPDS realm

The system SHALL protect the OPDS endpoints with HTTP Basic authentication in a dedicated realm using credentials configurable independently of the web-UI login, compatible with standard OPDS reader clients. The OPDS password SHALL be changeable from Settings by an authenticated web session supplying the current *admin* password, without affecting web or API credentials. At boot, the system SHALL re-seed the OPDS password only when `FORAGERR_OPDS_PASSWORD` is set and differs from a stored fingerprint of the value as last seeded — independent of the admin re-seed, so a stale OPDS env value never clobbers an in-app OPDS password change. Basic verification MAY cache positive verification results in-process for a short TTL; negative results SHALL never be cached, and any credential change SHALL clear the cache immediately.

- **Milestone**: M8
- **Source**: mylar-feature-surface.md §8 ("OPDS gets its own Basic-auth realm"); mylar-opds.md (not re-read here — OPDS AREA owns catalog behavior); m8-auth-core gate deferral (verify-cache), 2026-07-12.
- **Notes**: Basic is the only auth OPDS readers reliably support — keep it scoped to OPDS routes only. Basic credentials verify against a KDF hash like the web password; readers send Basic on every request, hence the positive-only short-TTL cache over the scrypt verify. Cache keys are hashes of presented credentials; plaintext is never stored.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** An OPDS client (iPad reader) prompts for and succeeds with the OPDS credentials; web-UI credentials are not required to differ but OPDS access works without a web session; a wrong password yields 401 with the realm header.

#### Scenario: OPDS password changes independently in Settings

- **WHEN** the operator sets a new OPDS password from Settings, supplying the correct admin password
- **THEN** OPDS requests with the old Basic credentials return 401 immediately (the verify-cache is cleared), the new credentials succeed, and the web session and API key remain valid and unchanged

#### Scenario: Changed OPDS env value re-seeds independently

- **WHEN** the deployment boots with `FORAGERR_OPDS_PASSWORD` set to a value that differs from the fingerprint of the value as last seeded
- **THEN** the OPDS password is re-seeded to the env value (OPDS-lockout recovery) without touching web sessions or the admin credentials — and conversely, a boot where the env value matches the fingerprint leaves an in-app OPDS password change in force

#### Scenario: Wrong Basic credentials are never cached

- **WHEN** an OPDS client repeatedly presents wrong Basic credentials and then the correct ones
- **THEN** every wrong presentation is verified afresh and refused with 401, and the correct presentation succeeds — a failed verify never poisons or displaces a cached positive entry

### Requirement: FRG-AUTH-006 — API keys separate from session auth

The system SHALL authenticate programmatic API access via an API key (X-Api-Key header) that is independent of web sessions and OPDS credentials, generated by the system (not user-chosen), and required on all API routes once auth is enabled.

- **Milestone**: M8
- **Source**: mylar-feature-surface.md §8 API/AUTH ("apikey-authenticated command API ... separate from web login"); sonarr-architecture.md §7.2 (X-Api-Key header or query).
- **Notes**: Divergence from Sonarr: header-only, no `apikey=` query parameter — keys in URLs leak into logs (same rationale as the ComicVine key-in-URL finding). Divergence from Mylar: no separate download-only key needed — foragerr uploads NZBs to SAB via `mode=addfile` (sonarr-architecture.md §4.2), so SAB never fetches from our API.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** API calls with the key succeed with no session; without it they return 401; the key works while the web password changes.

### Requirement: FRG-AUTH-007 — API key lifecycle

The system SHALL support regenerating (rotating) the API key from the UI/config, with the old key invalid immediately, and SHALL display the raw key only to an authenticated UI session and only at the moment of generation (bootstrap one-shot or rotation response) — afterwards the key SHALL NOT be retrievable in any form, with Settings showing only non-secret metadata (e.g., rotated-at). Rotation SHALL require re-authentication with the current admin password.

- **Milestone**: M8
- **Source**: mylar-feature-surface.md §8 API (tiered keys, getAPI bootstrap — bootstrap-from-credentials deliberately dropped); m8-auth pre-design (display-once, single key).
- **Notes**: Single key (not a key table) is sufficient for a single-user system; a multi-key/scoped model is backlog. Mylar's `getAPI` credentials-to-key bootstrap is NOT carried (obtains secrets over a GET — poor pattern). Stored as SHA-256 of the high-entropy random key (no KDF needed); no last-N hint is persisted. Re-auth on rotation means a ridden session cannot mint a durable credential.

#### Scenario: Rotation invalidates the old key immediately

- **WHEN** the operator rotates the API key from Settings, supplying the correct admin password
- **THEN** the rotation response carries the new raw key exactly once, calls with the old key return 401 from the next request onward, and calls with the new key succeed

#### Scenario: The key is display-once

- **WHEN** the Settings page is loaded after a rotation has completed (or after the bootstrap one-shot was consumed)
- **THEN** no endpoint returns the raw key in any form — Settings shows only non-secret metadata — and an unauthenticated or API-key-authenticated caller cannot reach the rotation or metadata endpoints at all

#### Scenario: Rotation requires re-authentication

- **WHEN** a rotation request is submitted with a valid session but a wrong or missing admin password
- **THEN** the request is refused with the same generic failure as any re-auth miss, the key is unchanged, and the refusal is logged as a structured event without credential material

### Requirement: FRG-AUTH-008 — at-rest secret encryption

The system SHALL store replayable secrets it persists (outbound service keys entered via UI, store-account credentials, OPDS/Basic credentials if reversibly needed, session signing material) encrypted with authenticated encryption under a key held outside the database, not obfuscated. The encryption key SHALL be derived from the `FORAGERR_SECRET_KEY` environment passphrase via scrypt with a random per-deployment salt; the salt and a sentinel check-value are persisted in a dedicated keystore meta table (both non-secret). The passphrase SHALL be supplied via the environment only and SHALL never be stored in a file under `/config` or elsewhere in the deployment. Ciphertext SHALL be stored in-place in the existing secret fields in the format `enc:v1:<token>` using Fernet, wrapped in MultiFernet so a future key rotation requires no storage-format change. Secret fields SHALL be identified by their existing `SecretStr` annotations, so any newly added persisted secret is encrypted with no per-provider work.

- **Milestone**: M6 (moved from M5 by roadmap-reshape, 2026-07-10 — the sources milestone stores store-account credentials, e.g. Humble Bundle, which require this control before they exist; application auth remains M8)
- **Source**: mylar-feature-surface.md §7 ("at-rest obfuscation of secrets ... salted-base64 ^~$z$ marker") — explicit better-than-Mylar divergence; mylar-ddl.md §4 (plaintext cookie storage); owner direction 2026-07-10 (env-only key; RISK-041 note); owner decisions 2026-07-11 (mandatory key, passphrase+KDF, fail-soft — see FRG-AUTH-011/012/013).
- **Notes**: Primary secret path remains env vars (DEP) — this covers whatever the app itself persists. Key from env means the DB file alone (e.g., in a backup) does not expose secrets. Losing the passphrase costs re-entry of stored secrets, never data (every stored secret is operator-re-obtainable; see FRG-AUTH-012). Key-rotation edge cases (re-encryption path, restores across rotation, old-key grace) remain explicitly deferred to the user-accounts milestone (M8) and MUST be designed there; MultiFernet is the pre-paid hook.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** DB and config-file inspection reveals no plaintext or base64-decodable secret values; every persisted secret field carries the `enc:v1:` prefix; tampering with ciphertext is detected (authentication failure), not silently decoded

#### Scenario: Key never persisted

- **WHEN** the deployment's `/config` volume and the application's files are inspected after normal operation including a backup cycle
- **THEN** the encryption passphrase and the derived key appear in no file — only the non-secret salt and sentinel are persisted, and a backup restored without the environment passphrase cannot decrypt stored credentials

#### Scenario: New secret fields are covered automatically

- **WHEN** a future change adds a persisted `SecretStr` field to any provider or source settings model
- **THEN** that field's value is encrypted at rest with no keystore-specific code in the new provider

### Requirement: FRG-AUTH-011 — mandatory environment key at startup

The system SHALL refuse to start when `FORAGERR_SECRET_KEY` is absent or empty, failing during configuration validation with an error that names the variable, states that it is an operator-chosen passphrase, and shows how to set it. The check SHALL run before any migration or data access so a keyless boot changes nothing on disk.

#### Scenario: Missing key blocks startup

- **WHEN** foragerr starts without `FORAGERR_SECRET_KEY` in its environment
- **THEN** the process exits non-zero before serving any request or writing to the database, and the startup error names `FORAGERR_SECRET_KEY` and describes how to supply it

#### Scenario: Key present proceeds

- **WHEN** foragerr starts with a non-empty `FORAGERR_SECRET_KEY`
- **THEN** startup proceeds; the derived key exists only in process memory and is never logged (FRG-NFR-008 redaction registered)

### Requirement: FRG-AUTH-012 — decrypt failure degrades the integration, not the service

The system SHALL treat a stored secret that fails to decrypt (sentinel mismatch after a passphrase change, or a backup restored into a deployment with a different passphrase) as *credential unavailable* for the owning integration only: the application SHALL start and serve normally, the affected integration SHALL behave as unconfigured (no retry storm against providers), and a health warning SHALL identify the integration and state that the encryption key is missing or changed and the secret must be re-entered. Saving a secret SHALL always encrypt under the currently derived key, clearing the condition.

#### Scenario: Wrong key at boot

- **WHEN** foragerr boots with a passphrase that does not match the stored sentinel and encrypted provider secrets exist
- **THEN** the application starts; library browsing and OPDS work; each affected integration shows credential-unavailable in health with re-entry guidance; no decrypt error crashes startup

#### Scenario: Re-entry recovers

- **WHEN** the operator re-enters an affected provider secret through Settings
- **THEN** the value is encrypted under the current key, the provider works, and the health warning for that provider clears

### Requirement: FRG-AUTH-013 — plaintext secret migration on first keyed boot

The system SHALL, on the first boot with a working keystore, convert every existing plaintext persisted secret value to `enc:v1:` ciphertext, exactly once and idempotently (values already carrying the prefix are skipped), logging only the count of migrated values. The conversion SHALL also cover plaintext values reintroduced later (e.g., a pre-upgrade backup restored onto a keyed deployment).

#### Scenario: Upgrade migrates existing secrets

- **WHEN** a deployment with plaintext indexer/download-client secrets boots the first release containing the keystore, with a valid passphrase set
- **THEN** after startup every persisted secret field carries `enc:v1:` ciphertext, providers keep working unchanged, and the migration logs a count, never a value

#### Scenario: Restored plaintext backup re-migrates

- **WHEN** a backup taken before the keystore release is restored onto a keyed deployment and foragerr boots
- **THEN** the restored plaintext secret values are encrypted at that boot by the same idempotent pass

### Requirement: FRG-AUTH-009 — login rate limiting and audit

The system SHALL rate-limit failed authentication attempts on every credential-bearing path (login form, `X-Api-Key` header, OPDS Basic) using in-process sliding-window counters keyed per (client IP, surface): after a threshold of failures within the window (default 5 per 15 minutes) further attempts on that key SHALL be refused before any password-hash work with HTTP 429 and a `Retry-After` deadline. Each *recorded* failure — a failure that reached the credential check (the first over-threshold one, and each later one admitted after a prior deadline elapsed) — SHALL grow the deadline exponentially, capped at the window length; attempts arriving while a deadline is still active SHALL be refused cheaply without extending or resetting it (they do no password-hash work, so they add no new failure to escalate on). The effect is that sustained guessing is throttled to at most one credential check per escalating deadline. The refusal SHALL be temporary — no hard lockout exists, and correct credentials presented after the deadline SHALL succeed (single-operator tool: self-lockout is the greater risk; env re-seed remains the recovery of last resort). A successful authentication SHALL reset the counters for its key. Requests carrying no credential (including absent or expired session cookies) SHALL NOT count as failures. When the login UI receives the 429, it SHALL surface the throttling to the operator as a distinct wait-and-retry-later message — never the generic bad-credentials or unreachable-server message — so the user-facing guidance matches the documented backoff rather than inviting an immediate retry. A global per-surface counter SHALL make distributed failure patterns visible in the audit log without ever blocking. The system SHALL log authentication successes and failures and every credential-lifecycle action as structured audit events on the standard logging pipeline (visible in System → Logs), each carrying the event name, surface, and source IP — never credential material, and never unsanitized client-controlled strings (the submitted username is control-character-stripped and length-capped before logging). The audit helper SHALL be exception-safe: a failure to render any single audit event SHALL NOT propagate into the request it audits. Because per-request API-key success events would flood the log, successful API-key use SHALL instead be audited per source: the first successful API-key authentication from a source IP within the window emits an `auth.apikey_source_seen` event, and key rotation resets the seen-source state — a leaked key becomes visible in the audit trail the moment it is used from a new address (owner decision 2026-07-12).

- **Milestone**: M8
- **Source**: mylar-feature-surface.md §8 AUTH (no equivalent in Mylar — divergence); FRG-PROC-006 (attack-surface changes require STRIDE coverage); m8-auth pre-design §6 (backoff-not-lockout, event vocabulary, reset-on-success), 2026-07-12; v0.9.0 backstop review (client-surface + audit-exception-safety clarifications), 2026-07-12.
- **Notes**: Client IP is the direct connection address only — `X-Forwarded-For` is not trusted (no reverse proxy in the deployment model; revisit with DEP's TLS story). Counters are process-local and reset on restart (accepted; no persistence, no migration). The limiter check preceding the KDF also shields the deliberately constant-work scrypt paths from failure-flood CPU exhaustion. OPDS Basic successes are logged per verification (verify-cache fill), not per request, so a reader polling with valid credentials cannot flood the log. Event vocabulary: `auth.login.success/.failure`, `auth.logout`, `auth.password_changed`, `auth.opds_password_changed`, `auth.opds_success` (per verification/cache fill, mirroring `auth.opds_failure`), `auth.opds_failure`, `auth.apikey_failure`, `auth.apikey_source_seen`, `auth.apikey_rotated`, `auth.reauth_failed`, `auth.backoff_triggered`, `auth.reseed`, plus `auth.audit_failed` (the swallow-all guard's own fallback line) — the ad-hoc lines shipped by m8-auth-core/m8-keys-opds migrate into this shape.

#### Scenario: Failure burst is throttled with growing deadlines

- **WHEN** a client submits more failed login attempts from one address than the threshold allows within the window, and — after waiting out each refusal — continues to fail
- **THEN** attempts over the threshold are refused with 429 and a `Retry-After` header before any password hashing runs, each recorded failure grows the next deadline exponentially up to the window-length cap (attempts made during an active deadline are refused cheaply and do not themselves escalate it), and an `auth.backoff_triggered` audit event records the escalation

#### Scenario: No hard lockout — correct credentials succeed after the deadline

- **WHEN** a key that was throttled stops failing and, after its `Retry-After` deadline passes, presents correct credentials
- **THEN** authentication succeeds normally and the counters for that key reset — at no point does any credential enter a state where correct values are permanently refused

#### Scenario: Keys are isolated per client and surface

- **WHEN** one client address exhausts the failure threshold on one surface (e.g. a misconfigured reader looping on OPDS Basic)
- **THEN** other surfaces from the same address and the same surface from other addresses are unaffected — the operator's browser login is not throttled by the reader's Basic failures

#### Scenario: Credential-less requests never count

- **WHEN** a client repeatedly presents an expired or absent session cookie, or probes OPDS with no Authorization header
- **THEN** no failure counter increments — only requests carrying a wrong credential (login body, present `X-Api-Key`, decodable Basic header) count toward throttling

#### Scenario: The login UI surfaces throttling as wait-not-retry

- **WHEN** the login form's submission is refused with a 429 because the failed-attempt throttle has engaged
- **THEN** the form shows a distinct message telling the operator to wait before trying again — not the generic "invalid credentials" nor the generic "could not sign in, try again" — so the on-screen guidance matches the documented backoff instead of inviting an immediate retry

#### Scenario: Distributed failures stay visible without blocking

- **WHEN** failed attempts arrive from many distinct addresses such that no single (IP, surface) key crosses the enforcement threshold but the per-surface total crosses the global threshold
- **THEN** an `auth.backoff_triggered` audit event fires identifying the surface and the aggregate pattern, and no request is blocked by the global counter — spraying failures cannot lock the operator out

#### Scenario: Successes and failures are audited without credential material

- **WHEN** authentication succeeds or fails on any surface, or a credential-lifecycle action runs (logout, password change, OPDS password change, key rotation, re-auth refusal, env re-seed)
- **THEN** a structured audit event with the event name, surface, and source IP appears on the standard logging pipeline (visible in System → Logs), and no event ever contains password or key material

#### Scenario: A failing audit render never breaks the audited request

- **WHEN** an audit event cannot be rendered (e.g. a field value whose string conversion raises)
- **THEN** the failure is swallowed and recorded as an `auth.audit_failed` line, and the authentication or credential-lifecycle request being audited completes unaffected — the audit helper never propagates an exception into the auth path

#### Scenario: API-key use from a new source is audited once per window

- **WHEN** a request authenticates successfully with the API key from a source IP that has not successfully used the key within the window, and further requests then arrive from that same IP inside the window
- **THEN** the first request emits an `auth.apikey_source_seen` audit event carrying the source IP, the subsequent same-IP requests emit nothing, and a later key rotation resets the seen-source state so the next use from any IP is audited again

#### Scenario: Client-controlled strings cannot forge log lines

- **WHEN** a login attempt submits a username containing newlines, ANSI escapes, or other control characters; an oversized username; or a value crafted to look like extra `key=value` fields (e.g. embedded spaces and `surface=`/`ip=` tokens)
- **THEN** the audit event renders it stripped of control characters and truncated to the length cap, and any value carrying a space or `=` is quoted so it reads as a single field value — the log line structure cannot be broken (no second event on a new line) and no additional `key=value` field can be forged from inside the username

### Requirement: FRG-AUTH-010 — uniform coverage of all surfaces

Every HTTP surface (UI, API, OPDS, WebSocket) SHALL require its designated credential via a single auth dependency installed at the application root — routes are protected by construction, and exemption is an explicit act. The exempt list is fixed at exactly: the health endpoint, the login route, and the static assets required to render the login screen. The invariant SHALL be proven three ways: by construction (the root-level dependency covers any newly mounted router by default), by an exhaustive route-inventory test walking the live route table, and by end-to-end negative paths on every surface. The WebSocket handshake SHALL run the same auth dependency and refuse unauthenticated connections before upgrade.

- **Milestone**: M8
- **Source**: mylar-feature-surface.md §8 (Mylar's `/api` exempt-with-own-key pattern; per-surface auth); sonarr-architecture.md §7 (SignalR under API auth); m8-auth pre-design (three-way proof), 2026-07-11/12.
- **Notes**: The route-inventory test is the traceability-friendly way (FRG-PROC-004) to prevent the classic "new endpoint forgot the auth dependency" regression; the constructive root dependency prevents it existing in the first place. SPA shell/assets on the exempt list disclose only static UI code — every API call the shell makes is authenticated.

#### Scenario: Route inventory proves default-deny

- **WHEN** the route-inventory test walks every route registered on the application (including routers added after this change)
- **THEN** every route either appears on the fixed exempt list (health, login route, login static assets) or refuses a bare request with 401/403, and the test fails if any route is neither

#### Scenario: Each surface refuses its bare request

- **WHEN** unauthenticated requests are made end-to-end to a UI view, an API route, an OPDS catalog path, and a WebSocket upgrade
- **THEN** the UI redirects to login, the API returns 401, OPDS returns 401 with its Basic realm challenge, and the WebSocket handshake is refused before upgrade

#### Scenario: A newly mounted router is covered with zero thought

- **WHEN** a test mounts a new router with a probe route onto the application factory's app without any auth annotation
- **THEN** the probe route refuses bare requests, demonstrating the perimeter covers additions by construction

#### Scenario: Designated credential per surface

- **WHEN** each surface is exercised with its designated credential — session cookie on UI/API, `X-Api-Key` header on API, HTTP Basic on OPDS, session or API key on the WebSocket handshake
- **THEN** each succeeds with its designated credential and is refused with a wrong or missing one, and an API key presented as a query parameter is not accepted

