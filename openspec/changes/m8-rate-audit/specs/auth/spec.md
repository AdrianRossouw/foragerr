# AUTH delta — m8-rate-audit

## MODIFIED Requirements

### Requirement: FRG-AUTH-009 — login rate limiting and audit

The system SHALL rate-limit failed authentication attempts on every credential-bearing path (login form, `X-Api-Key` header, OPDS Basic) using in-process sliding-window counters keyed per (client IP, surface): after a threshold of failures within the window (default 5 per 15 minutes) further attempts on that key SHALL be refused before any password-hash work with HTTP 429 and a `Retry-After` deadline that grows exponentially with continued failures, capped at the window length. The refusal SHALL be temporary — no hard lockout exists, and correct credentials presented after the deadline SHALL succeed (single-operator tool: self-lockout is the greater risk; env re-seed remains the recovery of last resort). A successful authentication SHALL reset the counters for its key. Requests carrying no credential (including absent or expired session cookies) SHALL NOT count as failures. A global per-surface counter SHALL make distributed failure patterns visible in the audit log without ever blocking. The system SHALL log authentication successes and failures and every credential-lifecycle action as structured audit events on the standard logging pipeline (visible in System → Logs), each carrying the event name, surface, and source IP — never credential material, and never unsanitized client-controlled strings (the submitted username is control-character-stripped and length-capped before logging).

- **Milestone**: M8
- **Source**: mylar-feature-surface.md §8 AUTH (no equivalent in Mylar — divergence); FRG-PROC-006 (attack-surface changes require STRIDE coverage); m8-auth pre-design §6 (backoff-not-lockout, event vocabulary, reset-on-success), 2026-07-12.
- **Notes**: Client IP is the direct connection address only — `X-Forwarded-For` is not trusted (no reverse proxy in the deployment model; revisit with DEP's TLS story). Counters are process-local and reset on restart (accepted; no persistence, no migration). The limiter check preceding the KDF also shields the deliberately constant-work scrypt paths from failure-flood CPU exhaustion. OPDS Basic successes are logged per verification (verify-cache fill), not per request, so a reader polling with valid credentials cannot flood the log. Event vocabulary: `auth.login.success/.failure`, `auth.logout`, `auth.password_changed`, `auth.opds_password_changed`, `auth.opds_failure`, `auth.apikey_failure`, `auth.apikey_rotated`, `auth.reauth_failed`, `auth.backoff_triggered`, `auth.reseed` — the ad-hoc lines shipped by m8-auth-core/m8-keys-opds migrate into this shape.

#### Scenario: Failure burst is throttled with growing deadlines

- **WHEN** a client submits more failed login attempts from one address than the threshold allows within the window
- **THEN** subsequent attempts from that (IP, surface) key are refused with 429 and a `Retry-After` header before any password hashing runs, the refusal deadline grows exponentially with continued attempts up to the window-length cap, and an `auth.backoff_triggered` audit event records the escalation

#### Scenario: No hard lockout — correct credentials succeed after the deadline

- **WHEN** a key that was throttled stops failing and, after its `Retry-After` deadline passes, presents correct credentials
- **THEN** authentication succeeds normally and the counters for that key reset — at no point does any credential enter a state where correct values are permanently refused

#### Scenario: Keys are isolated per client and surface

- **WHEN** one client address exhausts the failure threshold on one surface (e.g. a misconfigured reader looping on OPDS Basic)
- **THEN** other surfaces from the same address and the same surface from other addresses are unaffected — the operator's browser login is not throttled by the reader's Basic failures

#### Scenario: Credential-less requests never count

- **WHEN** a client repeatedly presents an expired or absent session cookie, or probes OPDS with no Authorization header
- **THEN** no failure counter increments — only requests carrying a wrong credential (login body, present `X-Api-Key`, decodable Basic header) count toward throttling

#### Scenario: Distributed failures stay visible without blocking

- **WHEN** failed attempts arrive from many distinct addresses such that no single (IP, surface) key crosses the enforcement threshold but the per-surface total crosses the global threshold
- **THEN** an `auth.backoff_triggered` audit event fires identifying the surface and the aggregate pattern, and no request is blocked by the global counter — spraying failures cannot lock the operator out

#### Scenario: Successes and failures are audited without credential material

- **WHEN** authentication succeeds or fails on any surface, or a credential-lifecycle action runs (logout, password change, OPDS password change, key rotation, re-auth refusal, env re-seed)
- **THEN** a structured audit event with the event name, surface, and source IP appears on the standard logging pipeline (visible in System → Logs), and no event ever contains password or key material

#### Scenario: Client-controlled strings cannot forge log lines

- **WHEN** a login attempt submits a username containing newlines, ANSI escapes, or other control characters, or an oversized username
- **THEN** the audit event renders it stripped of control characters and truncated to the length cap — the log line structure cannot be broken or a second event forged from inside the field
