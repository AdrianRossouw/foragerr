# m8-rate-audit — tasks

## 1. Rate limiter core

- [x] 1.1 `auth/ratelimit.py`: sliding-window registry — per-(IP, surface) deques on `time.monotonic()`, threshold/window/backoff constants, exponential deadline with window-length cap, success-reset, 1024-key oldest-idle eviction, global per-surface observability counter
- [x] 1.2 Unit tests: window arithmetic, deadline growth + cap, key isolation, reset-on-success, eviction bound, global-counter-never-blocks (tag FRG-AUTH-009)

## 2. Audit helper + event migration

- [x] 2.1 `auth/audit.py`: `audit_event(event, request, surface, **fields)` → `foragerr.auth` logger, fixed `<event> key=value` shape, username sanitizer (control-strip + length cap), never credential material
- [x] 2.2 Migrate existing ad-hoc lines (`auth.reauth_failed`, `auth.password_changed`, `auth.opds_password_changed`, `auth.apikey_rotated`, bootstrap re-seed line) into the vocabulary; add `auth.login.success/.failure`, `auth.logout`, `auth.opds_failure`, `auth.apikey_failure`, `auth.backoff_triggered`
- [x] 2.4 `auth.apikey_source_seen`: TTL'd seen-set of source IPs for successful key use (window TTL, bounded, cleared on rotation) — first use from an IP audits, repeats silent; tests incl. rotation-resets-baseline (tag FRG-AUTH-009)
- [x] 2.3 Tests: every event fires where specified; log-injection (newline/ANSI/oversize username); negative scan — no password/key material in any captured record (tag FRG-AUTH-009)

## 3. Enforcement wiring

- [x] 3.1 Login route: limiter check before the constant-work KDF (429 + Retry-After), increment on failure, reset on success
- [x] 3.2 Perimeter API-key path: limiter check wraps lookup for *present* keys; increment on mismatch; 429 propagation
- [x] 3.3 Perimeter Basic path: limiter check after `_decode_basic`, before cache/KDF; increment on verify failure; throttled key gets 429, not the realm challenge
- [x] 3.4 Tests: per-surface 429 behavior, KDF-not-run-when-throttled (call counting), throttled-then-correct-succeeds-after-deadline, cookie-failure and credential-less exemptions (tag FRG-AUTH-009)

## 4. e2e

- [x] 4.1 Scripted bad-login burst → 429 + `auth.backoff_triggered` visible in logs; recovery after deadline; no credential material in captured logs; refresh acceptance report

## 5. Docs + traceability

- [x] 5.1 `docs/manual/admin/authentication.md`: throttling behavior, reader-visible 429, restart-resets-counters, no-lockout recovery story
- [x] 5.2 `docs/security/`: threat-model — brute-force mitigation, client-IP trust boundary (no XFF), log-injection hardening, scrypt CPU-burn shielding; risk-register touch
- [x] 5.3 Registry: FRG-AUTH-009 → implemented; matrix regen; roadmap M8 section update (consistency test)
- [x] 5.4 CHANGELOG v0.9.0 + `pyproject`/`package.json`/`uv.lock` version bumps
- [x] 5.5 SOUP: no dep changes — `tools/soup_check.py` exits 0

## 6. Gate + merge

- [x] 6.1 Full suite green (pytest + vitest + tsc + e2e via run.sh)
- [x] 6.2 Small/medium fleet + Codex with dedicated adversarial angle (bypass via key isolation/IP handling, backoff arithmetic, operator-DoS, log injection, credential leakage into logs)
- [x] 6.3 Apply gate findings; gitleaks re-scan appended to history-scan.md
- [ ] 6.4 Merge --no-ff to main, tag v0.9.0, gh release, archive change, delete branch
