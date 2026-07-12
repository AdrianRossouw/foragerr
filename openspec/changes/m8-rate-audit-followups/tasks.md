# m8-rate-audit-followups — tasks

## 1. Frontend 429 handling (the confirmed bug)

- [x] 1.1 `LoginScreen.tsx`: add a 429 branch that surfaces a throttle-specific message (backend body message and/or `Retry-After` seconds), not the generic "Try again"
- [x] 1.2 `LoginScreen.test.tsx`: a 429 case asserting the throttle message (include FRG-AUTH-009 in the test name)

## 2. Backend hardening

- [x] 2.1 `auth/audit.py`: wrap `audit_event` body in a swallow-all guard so it can never propagate into the auth path; test that a raising field value does not break the caller
- [x] 2.2 `auth/ratelimit.py`: cap the global observation deque at a small constant (O(threshold), not O(failures-in-window)); reclaim empty per-key deques in `retry_after`; existing unit tests stay green

## 3. Mechanical dedup (behavior-preserving)

- [x] 3.1 `auth/audit.py`: export one `client_ip` helper; `perimeter.py` and `routes.py` import it instead of their private copies
- [x] 3.2 `routes.py`: reuse the perimeter's throttle-raise helper instead of a hand-rolled `HTTPException(429)`; drop the now-unneeded `import math`

## 4. Docs

- [x] 4.1 `docs/security/threat-model.md`: one-line note that `request.client is None` collapses to the shared "unknown" bucket, same mitigation as S1

## 5. Verify + gate + release

- [x] 5.1 Full suite green (pytest + vitest + tsc + e2e via run.sh) — the refactors are proven behavior-preserving by the existing FRG-AUTH-009 suites
- [x] 5.2 Focused security/correctness review of the delta + Codex (login-429 path, refactor-preserves-behavior)
- [x] 5.3 CHANGELOG v0.9.1; `pyproject`/`uv.lock` bump; gitleaks re-scan appended
- [ ] 5.4 Merge --no-ff, tag v0.9.1, gh release, archive, delete branch
