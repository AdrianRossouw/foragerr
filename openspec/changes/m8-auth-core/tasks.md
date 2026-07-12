# m8-auth-core — tasks

Requirement tags per FRG-PROC-004: pytest `@pytest.mark.req("FRG-AUTH-002")`
etc.; vitest/playwright include the ID in the test name. Worktree discipline
per FRG-PROC-008 when fanned out.

## 1. Credential foundation (backend)

- [ ] 1.1 `auth/passwords.py`: scrypt hash/verify (per-credential 16-byte
      salts, constant-time compare); benchmark parameters on target hardware
      and record constants + rationale comment (FRG-AUTH-003)
- [ ] 1.2 Migration (next free number): `principal` table (username, password
      hash, OPDS password hash, API-key SHA-256, timestamps) + `sessions`
      table (token hash, principal FK, tier, created, last_seen, expiry)
- [ ] 1.3 Config: `FORAGERR_ADMIN_USER`/`FORAGERR_ADMIN_PASSWORD`
      (+ optional `FORAGERR_OPDS_PASSWORD`), session/remember-me timeouts,
      WS origin allowlist; fail-fast validation when no principal exists and
      the pair is absent — ordered beside the FRG-AUTH-011 keystore check;
      env values redaction-registered (FRG-AUTH-002)
- [ ] 1.4 Bootstrap seeding: first authed boot seeds principal + OPDS
      credential (env or =admin) + generated API key; changed env pair
      re-seeds and invalidates old sessions, logged without credential
      material (FRG-AUTH-002)

## 2. Sessions and login (backend)

- [ ] 2.1 `auth/sessions.py`: opaque 256-bit tokens, SHA-256 rows, two
      sliding tiers, token regeneration on login, server-side logout,
      password-change invalidation-except-acting (FRG-AUTH-004)
- [ ] 2.2 Login/logout routes: form login with remember-me flag, generic
      failure responses, HttpOnly SameSite=Lax cookie, `Secure` conditional
      on transport with documented decision (FRG-AUTH-002/004)
- [ ] 2.3 Session prune job on the existing scheduler (FRG-AUTH-004)

## 3. Perimeter (backend)

- [ ] 3.1 Root auth dependency accepting the designated credential per
      surface (session cookie; `X-Api-Key` header only; OPDS Basic realm
      verify); installed above all routers in the app factory; exempt list
      exactly /health + login route + login static assets (FRG-AUTH-010)
- [ ] 3.2 CSRF stance: Origin/Referer check on unsafe methods under cookie
      auth (FRG-SEC-005)
- [ ] 3.3 WebSocket handshake: same auth dependency + Origin allowlist,
      refusal pre-upgrade (FRG-AUTH-010, FRG-SEC-005)

## 4. Frontend

- [ ] 4.1 Login screen (username/password/remember-me, tokens-compliant,
      minimal) + logout control
- [ ] 4.2 API client 401 interception → login redirect with return path;
      WS client re-auth handling

## 5. Tests (tagged per requirement)

- [ ] 5.1 Route-inventory test: every registered route exempt-listed or
      refuses bare requests; new-router probe covered by construction
      (FRG-AUTH-010)
- [ ] 5.2 Password/KDF tests: hash-only at rest, verify/reject,
      constant-time path, no credential material in logs (FRG-AUTH-003)
- [ ] 5.3 Session tests: cookie attributes, tier sliding expiry, fixation
      regeneration, logout replay 401, password-change invalidation, prune
      (FRG-AUTH-004)
- [ ] 5.4 Bootstrap tests: fail-fast without env pair, seed, re-seed
      recovery + session invalidation (FRG-AUTH-002)
- [ ] 5.5 CSRF + WS Origin tests: foreign-Origin unsafe method rejected,
      API-key surface immune, cross-origin WS refused pre-upgrade,
      configurable proxy origin (FRG-SEC-005)
- [ ] 5.6 Frontend tests: login flow, 401 redirect, logout (IDs in names)
- [ ] 5.7 e2e: negative paths per surface (UI/API/OPDS/WS refused bare),
      login + remember-me flow; add authenticated-session setup helper so
      existing scenarios stay green (FRG-AUTH-010, UAT negative-paths rule)

## 6. Docs, security, release

- [ ] 6.1 `docs/security/`: STRIDE session/cookie/CSRF rows; RISK-020
      Accept → Mitigated; RISK-022/G-5 closed; secrets docs gain
      "environment trust class" section (FRG-PROC-006)
- [ ] 6.2 `docs/manual/`: login, remember-me, env bootstrap + recovery,
      upgrade/BREAKING block; README auth-posture labelling if touched
      (FRG-PROC-011)
- [ ] 6.3 CHANGELOG v0.7.0 entry (BREAKING upgrade block) + backend
      pyproject bump (FRG-PROC-013)
- [ ] 6.4 Verify `soup_check` 0 (no dependency changes) and `trace.py` 0
      with the new tags; registry flips (AUTH-002/003/004/010 + SEC-005 →
      implemented; AUTH-001 → retired) staged for merge (FRG-PROC-005)

## 7. Gate

- [ ] 7.1 Full suites green (backend, frontend, e2e) on the branch
- [ ] 7.2 Security-touching gate: full eight-angle fleet + Codex full-diff,
      adversarial angles on perimeter bypass and session/CSRF handling with
      executed abuse scenarios (tiered-gates standard)
- [ ] 7.3 Merge-gate checklist → merge --no-ff → tag v0.7.0 + gh release →
      archive change → delete branch
