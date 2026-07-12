# AUTH delta — m8-keys-opds

## MODIFIED Requirements

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
