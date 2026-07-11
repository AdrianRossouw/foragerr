# m6-keystore — tasks

## 1. Keystore core

- [ ] 1.1 Add `cryptography` dependency + SOUP entry in `docs/security/soup-register.md`; `tools/soup_check.py` green
- [ ] 1.2 `foragerr/keystore.py`: scrypt derivation (documented parameters), MultiFernet wrapper, `encrypt()`/`decrypt()` with `enc:v1:` framing, sentinel create/verify; unit tests incl. tamper detection (`@pytest.mark.req("FRG-AUTH-008")`)
- [ ] 1.3 Alembic migration (next free number — 0016 claimed by M5 creators): `keystore_meta` single-row table (salt, sentinel, created_at)
- [ ] 1.4 Config validation: require non-empty `FORAGERR_SECRET_KEY` before migrations/data access, actionable error, redaction-register the passphrase; tests for missing/empty/present (`FRG-AUTH-011`)

## 2. Secret field integration

- [ ] 2.1 Encrypt at dump / decrypt at load in `indexers/repo.py` settings helpers via `SecretStr` field detection; mirror in `downloads/repo.py`
- [ ] 2.2 Decrypt-failure path: credential-unavailable state per row, integration behaves as unconfigured (no provider retries), health check contribution with re-entry guidance; wrong-key boot test proves startup + library/OPDS unaffected (`FRG-AUTH-012`)
- [ ] 2.3 Re-entry re-encrypts under current key and clears the health warning; test (`FRG-AUTH-012`)
- [ ] 2.4 Eager boot migration: idempotent plaintext→`enc:v1:` pass over indexer/download-client settings, count-only logging; tests for fresh upgrade AND restored-plaintext-backup re-migration (`FRG-AUTH-013`)

## 3. Verification sweep

- [ ] 3.1 Baseline acceptance test: DB dump contains no plaintext/base64-decodable secrets after normal operation + backup cycle; salt/sentinel are the only keystore artifacts on disk (`FRG-AUTH-008`)
- [ ] 3.2 Auto-coverage test: a synthetic settings model with a new `SecretStr` field round-trips encrypted with no provider-specific code (`FRG-AUTH-008`)
- [ ] 3.3 Startup-latency check: scrypt parameters keep boot within FRG-NFR-001 budget
- [ ] 3.4 Downgrade behavior verified: pre-keystore binary treats `enc:v1:` values as invalid credentials (unconfigured/test-fails), no crash — documented result in design.md rollback note

## 4. Docs, security, traceability

- [ ] 4.1 `docs/manual/admin/secrets.md`: close the "not yet covered" gap; document `FORAGERR_SECRET_KEY`, generated-value recommendation, lost-key recovery (re-entry)
- [ ] 4.2 `docs/manual/admin/configuration.md` + `deployment.md`: compose example gains the env var; **BREAKING** upgrade note
- [ ] 4.3 `docs/security/risk-register.md`: RISK-041 Accept → Mitigated (residual: weak passphrase note); RISK-013 status update; threat-model secrets section updated
- [ ] 4.4 Registry: flip FRG-AUTH-008 approved→implemented, FRG-AUTH-011..013 proposed→implemented; regenerate traceability matrix
- [ ] 4.5 CHANGELOG + release notes with the breaking upgrade section; version bump

## 5. Gate

- [ ] 5.1 Full suite green; tiered review gate (security-touching → full fleet + adversarial angle with a tested leak scenario + Codex) per docs/process/commit-standard.md merge-gate checklist
