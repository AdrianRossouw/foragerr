# m6-keystore — design

## Context

UI-entered provider secrets are `SecretStr` fields inside pydantic settings models,
serialized to canonical JSON in `indexers/repo.py` (`json.dumps(..., sort_keys=True)`
with `get_secret_value()` at dump) and mirrored in `downloads/repo.py`; the JSON lands
in the `settings` Text column of `IndexerRow` / `DownloadClientRow`. Redaction
(FRG-NFR-008) and write-only GET behavior already exist; at-rest the values are
plaintext (RISK-041). The schema layer (`indexers/schema.py`) already knows which
fields are secret via `SecretStr` annotations — this design reuses that single source
of truth, so new secret fields (e.g. the Humble cookie in the follow-up change) are
encrypted automatically with no per-provider work.

All decisions below were made by the owner on 2026-07-10/11; this document records
mechanics and rationale, not open choices.

## Goals / Non-Goals

**Goals:**
- No plaintext or reversibly-encoded secret in the DB, config, or any backup of them.
- One keystore that every current and future persisted secret flows through.
- Lost/changed key degrades the affected integrations, never the service or library.
- Rotation-ready layout (MultiFernet) without implementing rotation.

**Non-Goals:** key rotation workflow (M8); env/config-file-sourced secrets
(ComicVine key — operator-file trust class); whole-DB encryption; the Humble
importer (follow-up change).

## Decisions

1. **Key source: mandatory env passphrase** (`FORAGERR_SECRET_KEY`, any non-empty
   string). *Why mandatory over optional/gated*: owner decision — one code path, no
   plaintext/encrypted mixed states, closes RISK-041 outright; the breaking upgrade
   is a one-line env addition. *Why passphrase over strict Fernet key*: operator
   friendliness; scrypt (interactive-hardened parameters, e.g. n=2^15, r=8, p=1)
   makes offline brute-force of a stolen backup expensive, and the threat model is
   exactly "backup file without deployment env".
2. **Derivation: scrypt(passphrase, salt) → Fernet key.** Salt: 16 random bytes,
   generated once, stored in a new `keystore_meta` single-row table (salt is
   non-secret; it only prevents rainbow precomputation). Alongside it a **sentinel**:
   a fixed plaintext encrypted at keystore init. On boot, sentinel decrypt success ⇒
   key is right; failure ⇒ key changed (drives FRG-AUTH-012 health messaging,
   distinguishing wrong-key from row corruption, which Fernet's HMAC also detects).
3. **Cipher: Fernet via MultiFernet([derived_key]).** Authenticated encryption
   (AES-CBC + HMAC-SHA256), misuse-resistant API, and MultiFernet is the pre-paid M8
   rotation hook: rotation later = prepend new key, `rotate()` rows, no schema or
   format change.
4. **Storage format: in-place `enc:v1:<fernet-token>`** inside the existing settings
   JSON string values. *Why in-place over a secrets table*: no FK/joins, no dual
   write path, provider rows stay self-contained; the `enc:v1:` prefix makes
   encrypted-vs-legacy unambiguous and versions the format. Encrypt/decrypt lives in
   the two repo dump/load helpers — the only places `get_secret_value()` is called
   at persistence time. Because the prefix is reserved, the API input boundary
   rejects (422) a user-supplied secret whose value literally begins with `enc:v1:`,
   which would otherwise be stored verbatim as plaintext (the encrypt guard treats it
   as already-ciphertext) and become unreadable on load.
5. **Boot behavior**: key absent → fail startup during config validation
   (FRG-NFR-009 pattern) with an error naming the variable and one-line fix.
   Key present → derive once, hold in process memory only. Sentinel mismatch or row
   decrypt failure → **fail-soft** (FRG-AUTH-012): keystore marks affected rows
   unavailable; owning integration behaves as unconfigured and contributes a health
   warning ("credential unavailable — encryption key missing or changed; re-enter the
   secret"). Saving a secret always encrypts under the current key. Rationale: every
   stored secret is re-obtainable, so availability of the library/OPDS wins.
6. **Migration**: an alembic migration (next free number at implementation — 0016
   was claimed by the M5 creators backbone) creates `keystore_meta` only. Data migration
   (plaintext → `enc:v1:`) runs **at first keyed boot, not in alembic** — alembic
   contexts don't reliably have the env key, and boot-time migration can use the live
   keystore. Idempotent by prefix check; one-way; logged (count only, no values). The
   boot migration runs ONLY when the derived key matches the stored keystore (sentinel
   OK): a wrong-key boot defers it, so a restored plaintext row is never encrypted under
   a mismatched key (which the correct key could then never decrypt). A fresh keystore
   created over stranded ciphertext (lost `keystore_meta`) is itself the key, so it does
   migrate.
7. **Dependency**: `cryptography` (the Fernet/scrypt implementation; already a
   transitive candidate via httpx extras but now a direct SOUP-registered
   dependency). Vanilla stdlib has no authenticated-encryption primitive.

## Risks / Trade-offs

- [Weak passphrase weakens backup confidentiality] → scrypt cost parameters; docs
  recommend a generated value (`openssl rand -base64 32` example in secrets.md);
  residual risk noted on RISK-041's mitigation entry.
- [Operator loses the passphrase] → by design: fail-soft + re-entry (FRG-AUTH-012);
  documented recovery path in secrets.md ("re-enter provider secrets").
- [Restore of a pre-upgrade (plaintext) backup onto a keyed deployment] → boot
  migration re-runs by prefix check and encrypts the restored plaintext rows —
  covered by an explicit test.
- [scrypt at every boot adds latency] → parameters chosen ≤ ~100 ms on target
  hardware; measured against FRG-NFR-001 startup budget. **Measured (task 3.3,
  2026-07-12):** the single boot-time `scrypt(n=2**15, r=8, p=1, dklen=32)`
  derivation runs ~42–68 ms (avg ~50 ms) on the development host — a one-shot
  cost well inside the startup budget. Guarded by
  `test_scrypt_boot_latency_within_budget` (a generous 2.0 s ceiling to stay
  CI-stable). The suite otherwise lowers `SCRYPT_N` for speed; the check pins the
  production `n=2**15` explicitly so it measures the real cost.
- [enc:v1 values leak into logs] → tokens are non-sensitive without the key, but
  redaction still registers decrypted values as today; no change to FRG-NFR-008
  guarantees.

## Migration Plan

1. Release notes: **BREAKING — set `FORAGERR_SECRET_KEY` before upgrading**; compose
   example updated; demo deployment env updated at rollout.
2. Upgrade boot: keystore-meta alembic migration → keystore init (salt+sentinel) → eager plaintext
   migration → normal startup.
3. Rollback: downgrading after migration leaves `enc:v1:` values a pre-keystore
   binary can't read → documented as "re-enter secrets after downgrade" (same
   fail-soft class; old releases treat the unparseable value as an invalid key and
   the integration shows unconfigured/test-fails, not a crash — verified before
   release).

   **Downgrade behaviour verified (task 3.4, 2026-07-12) by reasoning from the
   pre-change code path** (an old binary cannot be run here, so this is a
   code-evidence argument, not an execution): a pre-keystore release loads
   provider settings through the *old* `indexers/repo.load_settings` /
   `downloads/repo.load_settings`, which do `json.loads(...)` →
   `validate_settings(...)` → `register_row_secrets(...)` with **no decrypt
   step**. The secret fields are `SecretStr`, and pydantic accepts any string, so
   an `enc:v1:<token>` value is validated successfully and stored back into the
   model as the literal API key — `load_indexers`/`load_download_clients` do NOT
   raise, so the row loads "healthy" but carries a garbage credential. At use
   time the provider authenticates with that literal string and the upstream
   rejects it (a 401/invalid-key), which the existing provider back-off + health
   path already handles as a degraded/test-failing integration, never a crash.
   Net: an operator who downgrades sees affected integrations report bad
   credentials and re-enters them (they are then stored as plaintext again under
   the old binary) — exactly the documented "re-enter secrets after downgrade"
   outcome, in the same fail-soft class as FRG-AUTH-012. Evidence: the pre-change
   `load_settings` implementations contain no `enc:`/decrypt handling, and
   `NewznabSettings.api_key` / `SabnzbdSettings.api_key` are plain `SecretStr`
   with no format validator that would reject the token.

## Open Questions

_None — all decision points resolved by owner 2026-07-10/11; anything newly
discovered during implementation goes back through the gate._
