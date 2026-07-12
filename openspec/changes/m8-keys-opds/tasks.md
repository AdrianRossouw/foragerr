# m8-keys-opds — tasks

## 1. Backend: fingerprints + re-seed semantics (FRG-AUTH-002/005)

- [x] 1.1 Migration 0024: nullable `env_password_hash` + `env_opds_password_hash` columns on `principal`
- [x] 1.2 Rework `auth/bootstrap.py` re-seed: per-credential fingerprint comparison (admin pair; OPDS decoupled), NULL-fingerprint one-time fallback to live-hash comparison, fingerprints written on every seed/re-seed
- [x] 1.3 Tagged tests: stale-env no-revert (`FRG-AUTH-002`), changed-pair re-seed still works, NULL-fingerprint upgrade boot, OPDS env re-seed independence + stale-OPDS-env no-clobber (`FRG-AUTH-005`)

## 2. Backend: credential-lifecycle endpoints (FRG-AUTH-004/005/006/007)

- [x] 2.1 Re-introduce `invalidate_others(db, principal_id, acting_session_id)` in `auth/sessions.py`
- [x] 2.2 `POST /api/v1/auth/password` — re-auth with current password, scrypt re-hash, `invalidate_others`, clear OPDS verify-cache (admin creds may back OPDS default), structured log event
- [x] 2.3 `POST /api/v1/auth/opds-password` — re-auth with admin password, clear verify-cache, structured log event
- [x] 2.4 `POST /api/v1/auth/api-key/rotate` — re-auth, new 256-bit key, SHA-256 at rest, raw key in response once, structured log event
- [x] 2.5 `POST /api/v1/auth/logout-all` — delete all session rows incl. acting; `GET /api/v1/auth/credentials` — non-secret status (username, key rotated-at, opds-differs flag)
- [x] 2.6 Uniform generic re-auth failure (same response wrong-vs-missing password) + structured log on refusal
- [x] 2.7 Tagged tests: acting-session preserved / others die (`FRG-AUTH-004`), logout-all (`FRG-AUTH-004`), old key 401s + new works + display-once + re-auth required (`FRG-AUTH-007`), key survives web password change (`FRG-AUTH-006`), OPDS change independent of web/API (`FRG-AUTH-005`)

## 3. Backend: OPDS verify-cache (FRG-AUTH-005)

- [x] 3.1 Positive-only TTL cache (60 s, cap 8, hashed-credential keys) in the perimeter Basic path; clear on any principal credential write
- [x] 3.2 Tagged tests: hit avoids second scrypt verify, negative never cached, cleared on OPDS/admin change (immediate 401 for old creds)

## 4. Frontend: Settings → Security

- [x] 4.1 Security settings page: web-password card, OPDS-password card, API-key card (rotated-at + rotate + display-once modal w/ copy), sessions card (logout-all + confirm)
- [x] 4.2 API client methods + `mapApiError` field mapping for re-auth failures; logout-all rides the 401 interceptor to the login screen
- [x] 4.3 Vitest coverage with FRG IDs in test names (display-once modal never re-renders key: `FRG-AUTH-007`; password form clears + preserves session: `FRG-AUTH-004`)

## 5. e2e

- [x] 5.1 Password change: acting browser session survives, second context's session 401s (`FRG-AUTH-004`)
- [x] 5.2 Key rotation: old key 401 immediately, new key succeeds, key not retrievable after modal dismissed (`FRG-AUTH-007`)
- [x] 5.3 OPDS password change: old Basic 401, new succeeds, web session unaffected (`FRG-AUTH-005`)
- [x] 5.4 Logout-all lands on login screen; negative paths for re-auth misses (UAT negative-paths rule)

## 6. Docs + traceability

- [x] 6.1 `docs/manual/`: managing credentials in Settings; recovery semantics update (new-value-required); OPDS reader re-prompt guidance
- [x] 6.2 `docs/security/`: risk-register RISK-003 residual closes; threat-model notes (fingerprint-at-rest class, verify-cache exposure bounds)
- [x] 6.3 Registry: FRG-AUTH-005/006/007 → implemented; traceability matrix regen
- [x] 6.4 CHANGELOG v0.8.0 + `pyproject`/`package.json` version bumps; release-notes block for re-seed semantics
- [x] 6.5 SOUP: no dep changes — `tools/soup_check.py` exits 0

## 7. Gate + merge

- [ ] 7.1 Full suite green (pytest + vitest + tsc + e2e via run.sh)
- [ ] 7.2 Security-touching gate: full fleet + Codex, adversarial angles on credential-change authz, session preservation, cache invalidation
- [ ] 7.3 Apply gate findings; acceptance report refresh
- [ ] 7.4 Merge --no-ff to main, tag v0.8.0, gh release, archive change, delete branch
