# AUTH — Authentication Specification

## Purpose

Baseline requirements for authentication, mined from the
Phase 1 reference research (`docs/research/`). Baseline depth per the Phase 2 scope
decision: SHALL + coarse acceptance; scenario-level elaboration happens in the
milestone change that implements each requirement (FRG-PROC-003, FRG-PROC-009).
## Requirements
### Requirement: FRG-AUTH-001 — M1/M2 no-auth accepted risk

Until AUTH ships (M8, per the 2026-07-10 roadmap reshape), the system SHALL operate without authentication on the web UI, API, and OPDS surfaces, with this documented as an accepted risk in the risk register whose compensating control is Tailscale-only network exposure (see DEP).

- **Milestone**: M1
- **Source**: mylar-feature-surface.md §8 AUTH (auth modes incl. none); CLAUDE.md (Tailscale, FRG-PROC-006 security-is-spec'd).
- **Notes**: Deliberate: shipping "auth mode: none" as the only M1 mode. FRG-PROC-006 requires the STRIDE/risk-register update in the same change that adds any listener — this requirement makes the acceptance explicit rather than implicit.

#### Scenario: All surfaces respond without credentials in auth mode "none"

- **WHEN** the M1 application is running and requests are made to `/health` and to `/api/v1/*` routes with no credentials, session, or API key of any kind
- **THEN** the requests succeed (2xx per route semantics), and a route-inventory test asserts that no auth middleware or auth dependency is registered on the app or any route

#### Scenario: Accepted risk is recorded with its compensating control

- **WHEN** the risk register and deployment docs are inspected as part of the M1 change
- **THEN** `docs/security/risk-register.md` RISK-020 records the no-auth acceptance with owner approval, restated in this change with Tailscale-only exposure (FRG-DEP-011) cited as the compensating control (not a second independent acceptance), and deployment docs state the tailnet-only constraint

#### Scenario: No half-built auth code paths exist before the auth milestone

- **WHEN** the M1 codebase and OpenAPI document are inspected
- **THEN** no dormant login routes, password/credential fields, session machinery, or partially wired auth dependencies exist — auth mode "none" is the only mode present, with nothing latent for the auth milestone to accidentally half-enable

### Requirement: FRG-AUTH-002 — single-user web login

The system SHALL protect the web UI and API with a single-user username/password login (form-based session auth for the UI), with no anonymous access to any non-exempt endpoint once auth is enabled.

- **Milestone**: M8
- **Source**: mylar-feature-surface.md §8 AUTH ("forms+session login with timeout"); sonarr- architecture.md §7.2 (auth).
- **Notes**: Single-user by design (single-operator tool) — no user table beyond one principal, no roles. Exempt endpoints: health (DEP) and OPDS (own realm, below).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Unauthenticated browser requests to any UI/API route redirect to login /return 401; correct credentials establish a session; wrong credentials do not.

### Requirement: FRG-AUTH-003 — password storage with modern KDF

The system SHALL store the user password only as a salted hash using a modern password-hashing KDF (argon2id or bcrypt), never reversibly, and SHALL NOT log or echo it.

- **Milestone**: M8
- **Source**: mylar-feature-surface.md §7/§8 (Mylar stores passwords "optionally obfuscated" — salted-base64) — explicit divergence to real hashing.
- **Notes**: One of the two "better than Mylar's obfuscation" commitments (the other is at-rest secret encryption below — different mechanism: hashing for verification-only credentials, encryption for secrets that must be replayed outbound).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** DB/config inspection shows only the KDF hash; the verify path authenticates the correct password and rejects others; no plaintext appears in logs during login.

### Requirement: FRG-AUTH-004 — session management

The system SHALL issue authenticated sessions as HttpOnly, SameSite cookies with a configurable inactivity timeout, support explicit logout invalidating the session server-side, and invalidate existing sessions on password change.

- **Milestone**: M8
- **Source**: mylar-feature-surface.md §8 AUTH ("session login with timeout").
- **Notes**: `Secure` cookie flag is conditional on transport (Tailscale HTTPS story is DEP's); document the decision. CSRF posture for the API (API-key header requests are CSRF-immune; session-cookie UI needs SameSite or token) must be stated in the STRIDE update.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Session cookie carries HttpOnly/SameSite attributes; an idle session past timeout requires re-login; logout then back-button yields 401; password change kills other sessions.

### Requirement: FRG-AUTH-005 — HTTP Basic for OPDS realm

The system SHALL protect the OPDS endpoints with HTTP Basic authentication in a dedicated realm using credentials configurable independently of the web-UI login, compatible with standard OPDS reader clients.

- **Milestone**: M8
- **Source**: mylar-feature-surface.md §8 ("OPDS gets its own Basic-auth realm"); mylar-opds.md (not re-read here — OPDS AREA owns catalog behavior).
- **Notes**: Basic is the only auth OPDS readers reliably support — keep it scoped to OPDS routes only. Basic credentials verify against a KDF hash like the web password.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** An OPDS client (iPad reader) prompts for and succeeds with the OPDS credentials; web-UI credentials are not required to differ but OPDS access works without a web session; a wrong password yields 401 with the realm header.

### Requirement: FRG-AUTH-006 — API keys separate from session auth

The system SHALL authenticate programmatic API access via an API key (X-Api-Key header) that is independent of web sessions and OPDS credentials, generated by the system (not user-chosen), and required on all API routes once auth is enabled.

- **Milestone**: M8
- **Source**: mylar-feature-surface.md §8 API/AUTH ("apikey-authenticated command API ... separate from web login"); sonarr-architecture.md §7.2 (X-Api-Key header or query).
- **Notes**: Divergence from Sonarr: header-only, no `apikey=` query parameter — keys in URLs leak into logs (same rationale as the ComicVine key-in-URL finding). Divergence from Mylar: no separate download-only key needed — foragerr uploads NZBs to SAB via `mode=addfile` (sonarr-architecture.md §4.2), so SAB never fetches from our API.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** API calls with the key succeed with no session; without it they return 401; the key works while the web password changes.

### Requirement: FRG-AUTH-007 — API key lifecycle

The system SHALL support regenerating (rotating) the API key from the UI/config, with the old key invalid immediately, and SHALL display the key only to an authenticated UI session.

- **Milestone**: M8
- **Source**: mylar-feature-surface.md §8 API (tiered keys, getAPI bootstrap — bootstrap-from- credentials deliberately dropped).
- **Notes**: Single key (not a key table) is sufficient for a single-user system; a multi-key/scoped model is backlog. Mylar's `getAPI` credentials-to-key bootstrap is NOT carried (obtains secrets over a GET — poor pattern).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** After rotation, calls with the old key return 401 and the new key succeeds; the key is not retrievable without web authentication.

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

The system SHALL rate-limit failed authentication attempts (login, Basic, API key) with a backoff or temporary lockout, and SHALL log authentication successes and failures (without credential material) as structured audit events.

- **Milestone**: M8
- **Source**: mylar-feature-surface.md §8 AUTH (no equivalent in Mylar — divergence); FRG-PROC-006 (attack-surface changes require STRIDE coverage).
- **Notes**: Modest thresholds fine for a Tailscale-only single-user service; the point is the audit trail and defense-in-depth if exposure ever widens.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A scripted burst of bad logins is throttled/locked out per policy; the log shows auth-failure events with source IP and no password/key content.

### Requirement: FRG-AUTH-010 — uniform coverage of all surfaces

When auth is enabled, every HTTP surface (UI, API, OPDS, WebSocket) SHALL require its designated credential, with the exempt list fixed at exactly: health endpoint and static login assets; the exemption list SHALL be covered by tests.

- **Milestone**: M8
- **Source**: mylar-feature-surface.md §8 (Mylar's `/api` exempt-with-own-key pattern; per-surface auth); sonarr-architecture.md §7 (SignalR under API auth).
- **Notes**: The route-inventory test is the traceability-friendly way (FRG-PROC-004) to prevent the classic "new endpoint forgot the auth dependency" regression.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** An automated route-inventory test asserts every registered route is either behind an auth dependency or on the documented exempt list; WebSocket connections without auth are refused.

