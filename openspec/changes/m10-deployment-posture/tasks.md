# m10-deployment-posture — tasks

Security-touching change → full review fleet + Codex at the gate
(tiered-gates policy). Tests tag requirement ids (`@pytest.mark.req`).

## 1. Trusted proxy (FRG-SEC-007)

- [ ] 1.1 Config: `server.trusted_proxies` (list, default empty) with
      FRG-DEP-004 versioned config migration; env override per config
      conventions
- [ ] 1.2 Perimeter resolution: resolve effective scheme + client IP once
      per request (direct peer in list → honor X-Forwarded-Proto /
      rightmost non-trusted X-Forwarded-For; else ignore); stash on request
      scope
- [ ] 1.3 Consumers: cookie `Secure` from effective scheme
      (auth/routes.py), rate-limiter key (api/limits.py), audit `client_ip`
      (auth/audit.py) all read the resolved values
- [ ] 1.4 Tests: trusted-peer honored, untrusted-peer ignored (negative),
      default-empty unchanged, consumer consistency

## 2. Security headers (FRG-SEC-006)

- [ ] 2.1 Response-header middleware, outermost, HTTP scope only: baseline
      headers everywhere; SPA self-only CSP; deny-all CSP on API/OPDS/
      health; frame-ancestors via CSP + X-Frame-Options fallback
- [ ] 2.2 Tests: headers on 200/401/404/500 across surfaces; no
      `Access-Control-Allow-*` ever (incl. preflight OPTIONS); e2e green
      under the SPA CSP (loosening recorded in posture doc if required)

## 3. Disclosure hygiene (FRG-SEC-008 + MODIFIED FRG-DEP-007)

- [ ] 3.1 `/health` slims to overall status + failing component names;
      detailed payload moves to authenticated
      `/api/v1/system/health/components`; frontend consumption checked/
      updated
- [ ] 3.2 Unhandled-exception handler: generic envelope 500, traceback to
      structured log only; test raises from a route and asserts no
      traceback/class/path in body; no-debug-path assertion test
- [ ] 3.3 Tests for health minimization (unauthenticated body fields,
      failing-name-only on 503, authed detail parity)

## 4. Posture record (FRG-DEP-017) and security docs (FRG-PROC-006)

- [ ] 4.1 `docs/security/posture.md`: TLS delegation; at-rest classes +
      full-DB-encryption rejection + FDE recommendation; DoS envelope
      (NFR-014 + WS caps) incl. RISK-005 position; no-CORS; trusted-proxy
      risk; downgrade warning
- [ ] 4.2 STRIDE/threat-model + risk-register updates: trusted-proxy
      misconfiguration row; information-disclosure rows updated for health
      minimization; RISK-005 restated; RISK-008 re-affirmed; FRG-DEP-012
      re-accept decision recorded; `tools/risk_register_check.py` green
- [ ] 4.3 Manual deployment-security section (TLS stories, FDE, container
      run flags, trusted proxy + warning, downgrade note); README
      consistency check
- [ ] 4.4 `docs/roadmap.md`: M9 marked complete; M10 in progress (posture
      first, release-pipeline second)

## 5. Gate and release

- [ ] 5.1 Registry rows → `implemented`; regenerate traceability matrix;
      `trace.py` / `soup_check.py` / `risk_register_check.py` green
- [ ] 5.2 Full suite green (backend, frontend, e2e via run.sh incl.
      negative paths); full review fleet + Codex (security-touching tier);
      fixes applied
- [ ] 5.3 CHANGELOG + version bump on branch; merge `--no-ff`; tag; push;
      `gh release create` (per /release)
