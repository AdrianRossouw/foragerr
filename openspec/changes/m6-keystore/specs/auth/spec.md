# auth delta — m6-keystore

## MODIFIED Requirements

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

## ADDED Requirements

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
