# m4-logs-viewer — tasks

## 1. Setup

- [x] 1.1 Branch `change/m4-logs-viewer`; allocate FRG-API-021 / FRG-UI-024 /
      FRG-NFR-015 in the registry; codify tiered review gates in
      `docs/process/commit-standard.md` item 6 (owner decision 2026-07-10)

## 2. Backend

- [ ] 2.1 Ring-buffer logging handler (deque, formatted records, O(1),
      attached at startup AFTER the redaction filter) + `log_buffer_records`
      setting with fail-fast validation (FRG-NFR-015, FRG-NFR-009)
- [ ] 2.2 `GET /api/v1/log` — paged newest-first, `level` + `logger` prefix
      filters, empty-buffer OK (FRG-API-021)
- [ ] 2.3 Pytest per scenario incl. the registered-secret redaction proof
      (`@pytest.mark.req` tags for API-021 ×3, NFR-015 ×2)

## 3. Frontend

- [ ] 3.1 `/system/logs` screen: dense table (time, level pill, logger,
      message), level + logger filters, Follow toggle with ≥2s polling that
      stops on off/unmount, honest empty/error states (FRG-UI-024)
- [ ] 3.2 Sidebar SYSTEM nav gains Logs (FRG-UI-023 shipped-screens rule);
      vitest per scenario (FRG-UI-024 in names)

## 4. Docs & security

- [x] 4.1 `docs/security/` STRIDE + risk register row for the log read
      endpoint (info disclosure; redaction-before-buffer mitigation)
      (FRG-PROC-006)
- [x] 4.2 Manual: web-ui.md System section + admin troubleshooting note
      (FRG-PROC-011); no SOUP changes (`tools/soup_check.py` still 0)

## 5. Merge gate (SMALL + security-touching tier)

- [ ] 5.1 Full suites green; trace 0; soup 0; gitleaks re-scan appended
- [ ] 5.2 Tiered review: 2 targeted angles (backend correctness/bounds on
      the strong tier; test/trace audit on the cheap tier) + a DEDICATED
      adversarial secret-leak angle + Codex full-diff; fixes; CHANGELOG
      v0.4.3 + bump; sync delta; archive; merge; tag; push; release
