# auth Spec Delta

## MODIFIED Requirements

### Requirement: FRG-AUTH-002 — single-user web login

The system SHALL protect the web UI and API with a single-user username/password login (form-based session auth for the UI), with no anonymous access to any non-exempt endpoint. Login SHALL be mandatory — no auth-mode-none or other bypass configuration exists (owner decision 2026-07-11/12). The single principal SHALL be seeded from `FORAGERR_ADMIN_USER`/`FORAGERR_ADMIN_PASSWORD` at first authed boot; startup SHALL fail fast with an actionable error when they are absent and no principal exists, and a changed pair SHALL re-seed the principal at boot (the lockout-recovery path). No unauthenticated setup window SHALL exist at any point.

- **Milestone**: M8
- **Source**: mylar-feature-surface.md §8 AUTH ("forms+session login with timeout"); sonarr-architecture.md §7.2 (auth); m8-auth pre-design owner decisions (mandatory, env bootstrap), 2026-07-11/12.
- **Notes**: Single-user by design (single-operator tool) — no user table beyond one principal, no roles. Exempt endpoints: health (DEP), login route + its static assets; OPDS has its own realm (FRG-AUTH-005). **BREAKING** at upgrade: the release refuses first boot without the bootstrap env pair, mirroring the FRG-AUTH-011 keystore precedent.

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

- **WHEN** the deployment boots with a `FORAGERR_ADMIN_USER`/`FORAGERR_ADMIN_PASSWORD` pair that differs from the stored principal's credentials
- **THEN** the principal is re-seeded to the env values at boot (recovering a lost-password lockout), the re-seed is logged as a structured event without credential material, and existing sessions for the old credentials are invalidated

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

The system SHALL issue authenticated sessions as DB-backed opaque tokens delivered in HttpOnly, SameSite cookies, storing server-side only a hash of the token, with two sliding-expiry tiers — a standard session (configurable inactivity timeout, default 24 h) and an opt-in remember-me tier (configurable, default 90 d) selected on the login form. The system SHALL regenerate the session token at login, support explicit logout invalidating the session server-side, invalidate all other sessions on password change, and prune expired sessions on the existing scheduler.

- **Milestone**: M8
- **Source**: mylar-feature-surface.md §8 AUTH ("session login with timeout"); m8-auth pre-design owner decision (remember-me comfort tier), 2026-07-11/12.
- **Notes**: Opaque DB tokens (not signed cookies) make server-side logout and password-change invalidation row deletes and leave no signing material to manage. `Secure` cookie flag is conditional on transport (Tailscale HTTPS story is DEP's); document the decision. CSRF posture lives in FRG-SEC-005.

#### Scenario: Cookie attributes and server-side storage

- **WHEN** a session is established and the cookie and database row are inspected
- **THEN** the cookie is HttpOnly and SameSite=Lax with the raw 256-bit token only in the cookie, and the database stores only the token's SHA-256 hash with principal, tier, created/last-seen, and expiry

#### Scenario: Sliding expiry per tier

- **WHEN** a standard session sits idle past its inactivity timeout, and a remember-me session is used within its window
- **THEN** the idle standard session requires re-login, while the active remember-me session slides its expiry forward and stays valid up to its configured tier window

#### Scenario: Login regenerates, logout revokes server-side

- **WHEN** a user logs in (with any pre-existing session cookie present) and later logs out, then replays the old cookies
- **THEN** login issues a fresh token (the prior token no longer authenticates — fixation defense), and after logout the deleted session's cookie yields 401 on replay (back-button included)

#### Scenario: Password change invalidates other sessions

- **WHEN** the password is changed from an authenticated session while other sessions (including remember-me) exist
- **THEN** every other session row is deleted — subsequent requests on them return 401 — while the acting session remains valid

#### Scenario: Expired rows are pruned

- **WHEN** sessions pass their expiry and the scheduler's prune job runs
- **THEN** expired rows are removed from the sessions table and the table does not grow without bound

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

## REMOVED Requirements

### Requirement: FRG-AUTH-001 — M1/M2 no-auth accepted risk

**Reason**: The accepted-risk window this requirement governed ends with m8-auth-core: mandatory authentication now covers every surface, so operating without authentication is no longer a supported (or possible) configuration. RISK-020 flips Accept → Mitigated in the same change.

**Migration**: The requirement's protective intent inverts into FRG-AUTH-010's perimeter scenarios — the old "all surfaces respond without credentials" assertion becomes "every surface refuses bare requests", and the no-half-built-auth-paths scenario is superseded by the fully built perimeter. The registry row flips to `retired` (never reused, per FRG-PROC-002); deployment docs drop the tailnet-only compensating-control framing in favor of the auth upgrade block.
