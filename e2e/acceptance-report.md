# foragerr end-to-end acceptance report

_Generated from the Playwright JSON reporter by `e2e/scripts/acceptance-report.mjs` — do not edit by hand (FRG-PROC-010)._

- **Verdict:** GREEN
- **Scenarios:** 37 (36 pass, 0 fail, 1 skipped, 0 flaky, 0 not run)
- **Run started:** 2026-07-17T14:06:53.861Z
- **Duration:** 121.3s

## Scenario → requirement coverage

| Result | Scenario | FRG requirement ids |
| --- | --- | --- |
| PASS | authenticate: log in through the UI and save the session | — |
| PASS | FRG-PROC-010 FRG-DEP-007 FRG-DEP-001: first run is healthy and the SPA loads | FRG-DEP-001, FRG-DEP-007, FRG-PROC-010 |
| PASS | FRG-PROC-010 FRG-DEP-013: the seeded DDL pair ships disabled and is enabled as an explicit opt-in | FRG-DEP-013, FRG-PROC-010 |
| PASS | FRG-PROC-010 FRG-SER-005 FRG-UI-005: add a series from the ComicVine fixture lands issues | FRG-PROC-010, FRG-SER-005, FRG-UI-005 |
| PASS | FRG-PROC-010 FRG-UI-008: created indexers are visible in settings | FRG-PROC-010, FRG-UI-008 |
| PASS | FRG-PROC-010 FRG-UI-007 FRG-SRCH-001: interactive search renders verbatim rejection reasons | FRG-PROC-010, FRG-SRCH-001, FRG-UI-007 |
| PASS | FRG-PROC-010 FRG-DDL-010 FRG-DL-007 FRG-PP-009 FRG-PP-010: grab downloads, imports and renames into the library | FRG-DDL-010, FRG-DL-007, FRG-PP-009, FRG-PP-010, FRG-PROC-010 |
| PASS | FRG-PROC-010 FRG-UI-003 FRG-SER-009: the library browse shows the series with updated stats | FRG-PROC-010, FRG-SER-009, FRG-UI-003 |
| PASS | FRG-PROC-010 FRG-CRTR-001 FRG-UI-027: creator credits ingest end-to-end and render on the grid | FRG-CRTR-001, FRG-PROC-010, FRG-UI-027 |
| PASS | FRG-PROC-010 FRG-UI-018: the calendar renders an unconfigured-source week without error | FRG-PROC-010, FRG-UI-018 |
| PASS | FRG-PROC-010 FRG-OPDS-001 FRG-OPDS-002 FRG-OPDS-003 FRG-OPDS-005 FRG-OPDS-019: OPDS navigates to a byte-identical comic download and a reachable cover | FRG-OPDS-001, FRG-OPDS-002, FRG-OPDS-003, FRG-OPDS-005, FRG-OPDS-019, FRG-PROC-010 |
| SKIPPED | FRG-PROC-010: live SABnzbd tier (skipped — no credentials) | FRG-PROC-010 |
| PASS | FRG-PROC-019 FRG-UI-038: core screens carry zero serious/critical axe WCAG 2.1 A/AA violations | FRG-PROC-019, FRG-UI-038 |
| PASS | FRG-PROC-010 FRG-UI-015 FRG-IMP-022 FRG-IMP-023: library import scans a root, reviews matches and imports existing files in place without a download | FRG-IMP-022, FRG-IMP-023, FRG-PROC-010, FRG-UI-015 |
| PASS | FRG-AUTH-010 FRG-PROC-010: a bare API request (no credential) is refused 401 | FRG-AUTH-010, FRG-PROC-010 |
| PASS | FRG-AUTH-010 FRG-PROC-010: OPDS answers a bare request with a Basic realm challenge, then serves with Basic creds | FRG-AUTH-010, FRG-PROC-010 |
| PASS | FRG-SEC-005 FRG-PROC-010: a cookie-authed unsafe method with a foreign Origin is refused 403, and the X-Api-Key surface is immune | FRG-PROC-010, FRG-SEC-005 |
| PASS | FRG-AUTH-010 FRG-PROC-010: a logged-out UI visit to a protected route lands on the login screen | FRG-AUTH-010, FRG-PROC-010 |
| PASS | FRG-AUTH-002 FRG-PROC-010: a wrong password yields a generic error and establishes no session | FRG-AUTH-002, FRG-PROC-010 |
| PASS | FRG-AUTH-010 FRG-PROC-010: logging in returns the operator to the intended (return) path | FRG-AUTH-010, FRG-PROC-010 |
| PASS | FRG-AUTH-004 FRG-PROC-010: after logout the old session token is dead — replaying it yields 401 | FRG-AUTH-004, FRG-PROC-010 |
| PASS | FRG-AUTH-010 FRG-SEC-005 FRG-PROC-010: a logged-in browser establishes the authenticated WebSocket (real-time connection goes live) | FRG-AUTH-010, FRG-PROC-010, FRG-SEC-005 |
| PASS | FRG-PROC-010 FRG-API-011: History shows the grabbed and imported rows sharing a downloadId | FRG-API-011, FRG-PROC-010 |
| PASS | FRG-PROC-010 FRG-API-012: Wanted lists a monitored, published, fileless issue | FRG-API-012, FRG-PROC-010 |
| PASS | FRG-PROC-010 FRG-OPDS-013: OPDS Recent serves the imported issue file bytes | FRG-OPDS-013, FRG-PROC-010 |
| PASS | FRG-UI-029: an unconfigured Sources screen shows the Humble connect card and DevTools helper | FRG-UI-029 |
| PASS | FRG-UI-029: connecting with an invalid cookie surfaces an honest error and persists nothing | FRG-UI-029 |
| PASS | FRG-PROC-010 FRG-SCHED-002: library and command queue survive a container restart | FRG-PROC-010, FRG-SCHED-002 |
| PASS | FRG-PROC-010 FRG-UI-005: an unconfigured ComicVine key surfaces an actionable credential error, not "no results" | FRG-PROC-010, FRG-UI-005 |
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
| FRG-API-011 | PASS |
| FRG-API-012 | PASS |
| FRG-AUTH-002 | PASS |
| FRG-AUTH-004 | PASS |
| FRG-AUTH-005 | PASS |
| FRG-AUTH-006 | PASS |
| FRG-AUTH-007 | PASS |
| FRG-AUTH-009 | PASS |
| FRG-AUTH-010 | PASS |
| FRG-CRTR-001 | PASS |
| FRG-DDL-010 | PASS |
| FRG-DEP-001 | PASS |
| FRG-DEP-007 | PASS |
| FRG-DEP-013 | PASS |
| FRG-DL-007 | PASS |
| FRG-IMP-022 | PASS |
| FRG-IMP-023 | PASS |
| FRG-OPDS-001 | PASS |
| FRG-OPDS-002 | PASS |
| FRG-OPDS-003 | PASS |
| FRG-OPDS-005 | PASS |
| FRG-OPDS-013 | PASS |
| FRG-OPDS-019 | PASS |
| FRG-PP-009 | PASS |
| FRG-PP-010 | PASS |
| FRG-PROC-010 | PASS |
| FRG-PROC-019 | PASS |
| FRG-SCHED-002 | PASS |
| FRG-SEC-005 | PASS |
| FRG-SER-005 | PASS |
| FRG-SER-009 | PASS |
| FRG-SRCH-001 | PASS |
| FRG-UI-003 | PASS |
| FRG-UI-005 | PASS |
| FRG-UI-007 | PASS |
| FRG-UI-008 | PASS |
| FRG-UI-015 | PASS |
| FRG-UI-018 | PASS |
| FRG-UI-027 | PASS |
| FRG-UI-029 | PASS |
| FRG-UI-038 | PASS |

---

_Hermetic-fixture coverage has known limits: this run does NOT exercise multi-host DDL landing-page parsing/failover, real redirect chains, or real SABnzbd unless the live tier runs. See the **Coverage limits** section of `e2e/README.md` before over-reading this report._
