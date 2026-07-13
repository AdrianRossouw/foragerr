# auth — logout-failure-handling deltas

## MODIFIED Requirements

### Requirement: FRG-AUTH-004 — session management

The system SHALL issue authenticated sessions as DB-backed opaque tokens delivered in HttpOnly, SameSite cookies, storing server-side only a hash of the token, with two sliding-expiry tiers — a standard session (configurable inactivity timeout, default 24 h) and an opt-in remember-me tier (configurable, default 90 d) selected on the login form. The system SHALL regenerate the session token at login, support explicit logout invalidating the session server-side, and prune expired sessions on the existing scheduler. When account credentials change, the system SHALL invalidate sessions as follows: an env re-seed at boot invalidates every session; a user-initiated password change from Settings invalidates every session *except* the acting one; and a logout-all control SHALL delete every session including the acting one. The web UI SHALL treat a logout as complete only when the server confirms session termination: on confirmation it clears client auth state and returns to the login screen; on a failed logout request it SHALL NOT clear auth state or navigate away (the session may still be live and the HttpOnly cookie cannot be cleared client-side), and SHALL surface a retryable failure instead.

- **Milestone**: M8 (client logout-confirmation: logout-failure-handling)
- **Source**: mylar-feature-surface.md §8 AUTH ("session login with timeout"); m8-auth pre-design owner decision (remember-me comfort tier + logout-all as the shared-device recovery), 2026-07-11/12; dogfooding 2026-07-13 (a failed logout must not present as a successful one).
- **Notes**: Opaque DB tokens (not signed cookies) make server-side logout and password-change invalidation row deletes and leave no signing material to manage. `Secure` cookie flag is conditional on transport (Tailscale HTTPS story is DEP's); document the decision. CSRF posture lives in FRG-SEC-005. Logout-all requires no password re-auth (it grants nothing — pure session destruction — and is the shared-device recovery path); credential writes do require re-auth (see FRG-AUTH-005/007 and the change design). The client-confirmation rule closes a shared-device exposure: because the session cookie is HttpOnly, only a server-confirmed logout truly ends the session, so the UI must never report success without it.

#### Scenario: Cookie attributes and server-side storage

- **WHEN** a session is established and the cookie and database row are inspected
- **THEN** the cookie is HttpOnly and SameSite=Lax with the raw 256-bit token only in the cookie, and the database stores only the token's SHA-256 hash with principal, tier, created/last-seen, and expiry

#### Scenario: Sliding expiry per tier

- **WHEN** a standard session sits idle past its inactivity timeout, and a remember-me session is used within its window
- **THEN** the idle standard session requires re-login, while the active remember-me session slides its expiry forward and stays valid up to its configured tier window

#### Scenario: Login regenerates, logout revokes server-side

- **WHEN** a user logs in (with any pre-existing session cookie present) and later logs out, then replays the old cookies
- **THEN** login issues a fresh token (the prior token no longer authenticates — fixation defense), and after logout the deleted session's cookie yields 401 on replay (back-button included)

#### Scenario: Confirmed logout clears the client and returns to login

- **WHEN** the operator activates the logout control and the server confirms the session was terminated
- **THEN** the UI clears its client auth state and navigates to the login screen

#### Scenario: Failed logout keeps the session and offers retry

- **WHEN** the operator activates the logout control and the logout request fails (a 4xx/5xx or a network error, so server-side termination is unconfirmed)
- **THEN** the UI does NOT clear client auth state and does NOT navigate to the login screen, keeping the operator authenticated, and surfaces an accessible, retryable error — a subsequent successful logout then clears and returns to login as normal

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
