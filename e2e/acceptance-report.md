# foragerr end-to-end acceptance report

_Generated from the Playwright JSON reporter by `e2e/scripts/acceptance-report.mjs` — do not edit by hand (FRG-PROC-010)._

- **Verdict:** RED
- **Scenarios:** 43 (12 pass, 17 fail, 13 skipped, 1 flaky, 0 not run)
- **Flaky:** 1 scenario(s) failed then passed on retry (rescued, but not clean — see the FLAKY rows below).
- **Reporter stats:** 17 unexpected failure(s).
- **Run started:** 2026-07-30T03:12:50.583Z
- **Duration:** 199.4s

## Scenario → requirement coverage

| Result | Scenario | FRG requirement ids |
| --- | --- | --- |
| PASS | authenticate: log in through the UI and save the session | — |
| FLAKY | FRG-PROC-010 FRG-DEP-007 FRG-DEP-001: first run is healthy and the SPA loads | FRG-DEP-001, FRG-DEP-007, FRG-PROC-010 |
| PASS | FRG-PROC-010 FRG-DEP-013: the seeded DDL pair ships disabled and is enabled as an explicit opt-in | FRG-DEP-013, FRG-PROC-010 |
| PASS | FRG-PROC-010 FRG-SER-005 FRG-UI-005: add a series from the ComicVine fixture lands issues | FRG-PROC-010, FRG-SER-005, FRG-UI-005 |
| PASS | FRG-PROC-010 FRG-UI-008: created indexers are visible in settings | FRG-PROC-010, FRG-UI-008 |
| FAIL | FRG-PROC-010 FRG-UI-007 FRG-SRCH-001: interactive search renders verbatim rejection reasons | FRG-PROC-010, FRG-SRCH-001, FRG-UI-007 |
| SKIPPED | FRG-PROC-010 FRG-DDL-010 FRG-DL-007 FRG-PP-009 FRG-PP-010: grab downloads, imports and renames into the library | FRG-DDL-010, FRG-DL-007, FRG-PP-009, FRG-PP-010, FRG-PROC-010 |
| SKIPPED | FRG-PROC-010 FRG-UI-003 FRG-SER-009: the library browse shows the series with updated stats | FRG-PROC-010, FRG-SER-009, FRG-UI-003 |
| SKIPPED | FRG-PROC-010 FRG-CRTR-001 FRG-UI-027: creator credits ingest end-to-end and render on the grid | FRG-CRTR-001, FRG-PROC-010, FRG-UI-027 |
| SKIPPED | FRG-PROC-010 FRG-UI-018: the calendar renders an unconfigured-source week without error | FRG-PROC-010, FRG-UI-018 |
| SKIPPED | FRG-PROC-010 FRG-OPDS-001 FRG-OPDS-002 FRG-OPDS-003 FRG-OPDS-005 FRG-OPDS-019: OPDS navigates to a byte-identical comic download and a reachable cover | FRG-OPDS-001, FRG-OPDS-002, FRG-OPDS-003, FRG-OPDS-005, FRG-OPDS-019, FRG-PROC-010 |
| SKIPPED | FRG-PROC-010: live SABnzbd tier (skipped — no credentials) | FRG-PROC-010 |
| FAIL | FRG-PROC-019 FRG-UI-038: core screens carry zero serious/critical axe WCAG 2.1 A/AA violations | FRG-PROC-019, FRG-UI-038 |
| FAIL | FRG-PROC-010 FRG-UI-015 FRG-IMP-022 FRG-IMP-023: library import scans a root, reviews matches and imports existing files in place without a download | FRG-IMP-022, FRG-IMP-023, FRG-PROC-010, FRG-UI-015 |
| FAIL | FRG-PROC-010 FRG-SER-021 FRG-UI-045: a readable-but-unwritable root registers read-only while an ordinary registration of it is refused | FRG-PROC-010, FRG-SER-021, FRG-UI-045 |
| SKIPPED | FRG-PROC-010 FRG-SER-022 FRG-UI-045: a series added on a read-only root is unmonitored with no search dispatched | FRG-PROC-010, FRG-SER-022, FRG-UI-045 |
| SKIPPED | FRG-PROC-010 FRG-SER-022: search and monitoring for a read-only series are refused with the uniform 409, by route and by direct command | FRG-PROC-010, FRG-SER-022 |
| SKIPPED | FRG-PROC-010 FRG-IMP-028: library import indexes a read-only root in place, renaming and moving nothing | FRG-IMP-028, FRG-PROC-010 |
| SKIPPED | FRG-PROC-010 FRG-SER-021: file-mutating operations are refused and the read-only root stays untouched | FRG-PROC-010, FRG-SER-021 |
| SKIPPED | FRG-PROC-010 FRG-UI-045: the UI marks a read-only series and offers none of the refused actions | FRG-PROC-010, FRG-UI-045 |
| FAIL | FRG-AUTH-010 FRG-PROC-010: a bare API request (no credential) is refused 401 | FRG-AUTH-010, FRG-PROC-010 |
| FAIL | FRG-AUTH-010 FRG-PROC-010: OPDS answers a bare request with a Basic realm challenge, then serves with Basic creds | FRG-AUTH-010, FRG-PROC-010 |
| FAIL | FRG-SEC-005 FRG-PROC-010: a cookie-authed unsafe method with a foreign Origin is refused 403, and the X-Api-Key surface is immune | FRG-PROC-010, FRG-SEC-005 |
| FAIL | FRG-AUTH-010 FRG-PROC-010: a logged-out UI visit to a protected route lands on the login screen | FRG-AUTH-010, FRG-PROC-010 |
| FAIL | FRG-AUTH-002 FRG-PROC-010: a wrong password yields a generic error and establishes no session | FRG-AUTH-002, FRG-PROC-010 |
| FAIL | FRG-AUTH-010 FRG-PROC-010: logging in returns the operator to the intended (return) path | FRG-AUTH-010, FRG-PROC-010 |
| FAIL | FRG-AUTH-004 FRG-PROC-010: after logout the old session token is dead — replaying it yields 401 | FRG-AUTH-004, FRG-PROC-010 |
| FAIL | FRG-AUTH-010 FRG-SEC-005 FRG-PROC-010: a logged-in browser establishes the authenticated WebSocket (real-time connection goes live) | FRG-AUTH-010, FRG-PROC-010, FRG-SEC-005 |
| FAIL | FRG-PROC-010 FRG-API-011: History shows the grabbed and imported rows sharing a downloadId | FRG-API-011, FRG-PROC-010 |
| SKIPPED | FRG-PROC-010 FRG-API-012: Wanted lists a monitored, published, fileless issue | FRG-API-012, FRG-PROC-010 |
| SKIPPED | FRG-PROC-010 FRG-OPDS-013: OPDS Recent serves the imported issue file bytes | FRG-OPDS-013, FRG-PROC-010 |
| FAIL | FRG-UI-029: an unconfigured Sources screen shows the Humble connect card and DevTools helper | FRG-UI-029 |
| FAIL | FRG-UI-029: connecting with an invalid cookie surfaces an honest error and persists nothing | FRG-UI-029 |
| FAIL | FRG-PROC-010 FRG-SCHED-002: library and command queue survive a container restart | FRG-PROC-010, FRG-SCHED-002 |
| FAIL | FRG-PROC-010 FRG-UI-005: an unconfigured ComicVine key surfaces an actionable credential error, not "no results" | FRG-PROC-010, FRG-UI-005 |
| PASS | FRG-AUTH-005: OPDS password changes independently and old Basic creds die instantly | FRG-AUTH-005 |
| PASS | FRG-AUTH-007 FRG-AUTH-006: key rotation kills the old key immediately; re-auth required | FRG-AUTH-006, FRG-AUTH-007 |
| PASS | FRG-AUTH-004: password change preserves the acting session and kills every other | FRG-AUTH-004 |
| PASS | FRG-AUTH-004: logout-all destroys every session including the acting one | FRG-AUTH-004 |
| PASS | FRG-AUTH-009: a bad-login burst is throttled with 429 and a Retry-After deadline | FRG-AUTH-009 |
| PASS | FRG-AUTH-009: the audit trail records the failures and the backoff escalation, with no credential material | FRG-AUTH-009 |
| PASS | FRG-AUTH-009: no hard lockout — after the Retry-After deadline, correct credentials succeed and reset the counter | FRG-AUTH-009 |
| PASS | FRG-AUTH-009: OPDS Basic is throttled and isolated from the login surface (key isolation) | FRG-AUTH-009 |

## Requirement roll-up

| FRG id | Result |
| --- | --- |
| FRG-API-011 | FAIL |
| FRG-API-012 | SKIPPED |
| FRG-AUTH-002 | FAIL |
| FRG-AUTH-004 | FAIL |
| FRG-AUTH-005 | PASS |
| FRG-AUTH-006 | PASS |
| FRG-AUTH-007 | PASS |
| FRG-AUTH-009 | PASS |
| FRG-AUTH-010 | FAIL |
| FRG-CRTR-001 | SKIPPED |
| FRG-DDL-010 | SKIPPED |
| FRG-DEP-001 | FLAKY |
| FRG-DEP-007 | FLAKY |
| FRG-DEP-013 | PASS |
| FRG-DL-007 | SKIPPED |
| FRG-IMP-022 | FAIL |
| FRG-IMP-023 | FAIL |
| FRG-IMP-028 | SKIPPED |
| FRG-OPDS-001 | SKIPPED |
| FRG-OPDS-002 | SKIPPED |
| FRG-OPDS-003 | SKIPPED |
| FRG-OPDS-005 | SKIPPED |
| FRG-OPDS-013 | SKIPPED |
| FRG-OPDS-019 | SKIPPED |
| FRG-PP-009 | SKIPPED |
| FRG-PP-010 | SKIPPED |
| FRG-PROC-010 | FAIL |
| FRG-PROC-019 | FAIL |
| FRG-SCHED-002 | FAIL |
| FRG-SEC-005 | FAIL |
| FRG-SER-005 | PASS |
| FRG-SER-009 | SKIPPED |
| FRG-SER-021 | FAIL |
| FRG-SER-022 | SKIPPED |
| FRG-SRCH-001 | FAIL |
| FRG-UI-003 | SKIPPED |
| FRG-UI-005 | FAIL |
| FRG-UI-007 | FAIL |
| FRG-UI-008 | PASS |
| FRG-UI-015 | FAIL |
| FRG-UI-018 | SKIPPED |
| FRG-UI-027 | SKIPPED |
| FRG-UI-029 | FAIL |
| FRG-UI-038 | FAIL |
| FRG-UI-045 | FAIL |

## Failed scenarios

- **FRG-PROC-010 FRG-UI-007 FRG-SRCH-001: interactive search renders verbatim rejection reasons** (spine.spec.ts)
- **FRG-PROC-019 FRG-UI-038: core screens carry zero serious/critical axe WCAG 2.1 A/AA violations** (x-a11y.spec.ts)
- **FRG-PROC-010 FRG-UI-015 FRG-IMP-022 FRG-IMP-023: library import scans a root, reviews matches and imports existing files in place without a download** (y-library-import.spec.ts)
- **FRG-PROC-010 FRG-SER-021 FRG-UI-045: a readable-but-unwritable root registers read-only while an ordinary registration of it is refused** (y2-read-only-library.spec.ts)
- **FRG-AUTH-010 FRG-PROC-010: a bare API request (no credential) is refused 401** (z-auth-negative.spec.ts)
- **FRG-AUTH-010 FRG-PROC-010: OPDS answers a bare request with a Basic realm challenge, then serves with Basic creds** (z-auth-negative.spec.ts)
- **FRG-SEC-005 FRG-PROC-010: a cookie-authed unsafe method with a foreign Origin is refused 403, and the X-Api-Key surface is immune** (z-auth-negative.spec.ts)
- **FRG-AUTH-010 FRG-PROC-010: a logged-out UI visit to a protected route lands on the login screen** (z-auth-negative.spec.ts)
- **FRG-AUTH-002 FRG-PROC-010: a wrong password yields a generic error and establishes no session** (z-auth-negative.spec.ts)
- **FRG-AUTH-010 FRG-PROC-010: logging in returns the operator to the intended (return) path** (z-auth-negative.spec.ts)
- **FRG-AUTH-004 FRG-PROC-010: after logout the old session token is dead — replaying it yields 401** (z-auth-negative.spec.ts)
- **FRG-AUTH-010 FRG-SEC-005 FRG-PROC-010: a logged-in browser establishes the authenticated WebSocket (real-time connection goes live)** (z-auth-negative.spec.ts)
- **FRG-PROC-010 FRG-API-011: History shows the grabbed and imported rows sharing a downloadId** (z-daily-spine.spec.ts)
- **FRG-UI-029: an unconfigured Sources screen shows the Humble connect card and DevTools helper** (z-sources.spec.ts)
- **FRG-UI-029: connecting with an invalid cookie surfaces an honest error and persists nothing** (z-sources.spec.ts)
- **FRG-PROC-010 FRG-SCHED-002: library and command queue survive a container restart** (zz-restart.spec.ts)
- **FRG-PROC-010 FRG-UI-005: an unconfigured ComicVine key surfaces an actionable credential error, not "no results"** (zz-unconfigured.spec.ts)

## Flaky scenarios (rescued on retry)

- **FRG-PROC-010 FRG-DEP-007 FRG-DEP-001: first run is healthy and the SPA loads** (spine.spec.ts) — statuses: passed → failed

---

_Hermetic-fixture coverage has known limits: this run does NOT exercise multi-host DDL landing-page parsing/failover, real redirect chains, or real SABnzbd unless the live tier runs. See the **Coverage limits** section of `e2e/README.md` before over-reading this report._
