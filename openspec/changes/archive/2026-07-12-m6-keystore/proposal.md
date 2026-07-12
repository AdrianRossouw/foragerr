# m6-keystore — at-rest secret encryption (FRG-AUTH-008)

## Why

Provider secrets entered through the UI (indexer API keys, SABnzbd credentials) are
stored in plaintext in the SQLite database, and scheduled backups copy that database
verbatim — every backup file is credential-bearing (RISK-041, accepted for M2–M4 with
mitigation committed to land at M6 start). M6 is the sources milestone: the Humble
Bundle importer will persist a store-account session cookie, a strictly more sensitive
secret than any API key we hold today. The keystore must exist **before** any such
credential is persisted (2026-07-10 roadmap-reshape sequencing; owner design decisions
finalized 2026-07-11).

## What Changes

- **BREAKING**: foragerr requires a `FORAGERR_SECRET_KEY` environment variable at
  startup. It is an operator-chosen passphrase (any non-empty string), supplied via
  the environment only — never read from, or written to, any file under `/config`.
  Startup fails with a clear, actionable error when it is absent.
- A keystore derives a Fernet encryption key from the passphrase via scrypt, using a
  random non-secret salt persisted in a new DB meta table alongside a sentinel
  check-value that distinguishes wrong-key from corrupt-data.
- All UI-entered provider secrets (`SecretStr` fields inside indexer and
  download-client `settings` JSON) are encrypted with authenticated encryption
  (Fernet), stored in-place in the existing columns as `enc:v1:<token>` values.
  MultiFernet is used from day one so M8 key rotation needs no schema change.
- First boot after upgrade eagerly migrates existing plaintext secret values to
  `enc:v1:` ciphertext (one-way; the breaking release note covers this).
- **Decrypt-fail-soft**: a stored secret that fails to decrypt (changed passphrase,
  backup restored into a different deployment) does not prevent startup — the owning
  integration reports "credential unavailable — encryption key missing or changed"
  through the health system and behaves as unconfigured; re-entering the secret
  re-encrypts it under the current key. Every stored secret is re-obtainable by the
  operator, so a lost key costs re-entry, never data.
- New SOUP dependency: `cryptography` (Fernet/scrypt primitives).
- RISK-041 flips **Accept → Mitigated**; risk register and threat model updated.
- Manual updates: `docs/manual/admin/secrets.md` (the "not yet covered" gap closes),
  `configuration.md`, `deployment.md` (compose example + breaking upgrade note).

## Capabilities

### New Capabilities

_None — this lands within the existing `auth` capability._

### Modified Capabilities

- `auth`: FRG-AUTH-008 (at-rest secret encryption) moves from approved to
  implemented, refined with the decided mechanics (passphrase + scrypt KDF, salt +
  sentinel in DB meta, `enc:v1:` in-place format, MultiFernet rotation hook, eager
  plaintext migration). Three new requirements are allocated:
  - **FRG-AUTH-011 — mandatory environment key at startup**: boot refuses to proceed
    without `FORAGERR_SECRET_KEY`; the error names the variable and the fix.
  - **FRG-AUTH-012 — decrypt-failure degrades the integration, not the service**:
    fail-soft semantics, health surfacing, re-entry re-encrypts under the current key.
  - **FRG-AUTH-013 — plaintext secret migration on first keyed boot**: existing
    indexer/SAB secret values are converted to ciphertext exactly once, idempotently.

## Impact

- **Code**: new `foragerr/keystore.py` (derivation, encrypt/decrypt, sentinel);
  `indexers/repo.py` + `downloads/repo.py` settings dump/load paths; startup wiring in
  config validation (FRG-NFR-009 pattern); health check contribution; one alembic
  migration (keystore meta table; number assigned at implementation — 0016 went to
  M5 creators); eager data migration at boot, not in alembic
  (needs the env key, which alembic offline contexts don't have).
- **Dependencies**: `cryptography` added — `docs/security/soup-register.md` entry in
  the same change; `tools/soup_check.py` must stay green.
- **Security docs**: RISK-041 Accept → Mitigated; RISK-013 status note; threat-model
  §secrets updated. No new attack surface (no new listener/parser of untrusted input;
  the keystore consumes an operator-supplied env var), so no new STRIDE row — existing
  rows updated instead.
- **Operators / BREAKING**: every deployment must add `FORAGERR_SECRET_KEY` before
  upgrading; the demo deployment needs it too. Release notes carry a prominent
  upgrade section. Backups taken after this release require the same passphrase to
  yield usable credentials on restore — restoring without it degrades to re-entry
  (FRG-AUTH-012), never data loss.
- **Out of scope / Non-goals**: see below.

## Non-goals

- **Key rotation workflow** — re-encryption path, old-key grace list,
  restore-across-rotation semantics — explicitly deferred to M8 (user accounts), per
  owner direction 2026-07-10. MultiFernet layout is the pre-paid hook only.
- **ComicVine key and other env/config.yaml-sourced secrets** — those live in the
  operator-file trust class (same as `.env`); this change covers only what the app
  itself persists to the DB.
- **Encrypting non-secret settings** or whole-database encryption.
- **The Humble importer itself** — separate follow-up change; this lands first.

## Approval

**Approved by Adrian, 2026-07-11** (planning session). Scope as proposed: mandatory
env passphrase, scrypt+MultiFernet, `enc:v1:` in-place, decrypt-fail-soft, eager
migration; rotation stays M8. Implementation may begin at M6 start.
