# foragerr end-to-end acceptance report

_Generated from the Playwright JSON reporter by `e2e/scripts/acceptance-report.mjs` — do not edit by hand (FRG-PROC-010)._

- **Verdict:** GREEN
- **Scenarios:** 15 (14 pass, 0 fail, 1 skipped, 0 flaky, 0 not run)
- **Run started:** 2026-07-10T20:33:20.429Z
- **Duration:** 62.5s

## Scenario → requirement coverage

| Result | Scenario | FRG requirement ids |
| --- | --- | --- |
| PASS | FRG-PROC-010 FRG-DEP-007 FRG-DEP-001: first run is healthy and the SPA loads | FRG-DEP-001, FRG-DEP-007, FRG-PROC-010 |
| PASS | FRG-PROC-010 FRG-DEP-013: the seeded DDL pair ships disabled and is enabled as an explicit opt-in | FRG-DEP-013, FRG-PROC-010 |
| PASS | FRG-PROC-010 FRG-SER-005 FRG-UI-005: add a series from the ComicVine fixture lands issues | FRG-PROC-010, FRG-SER-005, FRG-UI-005 |
| PASS | FRG-PROC-010 FRG-UI-008: created indexers are visible in settings | FRG-PROC-010, FRG-UI-008 |
| PASS | FRG-PROC-010 FRG-UI-007 FRG-SRCH-001: interactive search renders verbatim rejection reasons | FRG-PROC-010, FRG-SRCH-001, FRG-UI-007 |
| PASS | FRG-PROC-010 FRG-DDL-010 FRG-DL-007 FRG-PP-009 FRG-PP-010: grab downloads, imports and renames into the library | FRG-DDL-010, FRG-DL-007, FRG-PP-009, FRG-PP-010, FRG-PROC-010 |
| PASS | FRG-PROC-010 FRG-UI-003 FRG-SER-009: the library browse shows the series with updated stats | FRG-PROC-010, FRG-SER-009, FRG-UI-003 |
| PASS | FRG-PROC-010 FRG-OPDS-001 FRG-OPDS-002 FRG-OPDS-003 FRG-OPDS-005: OPDS navigates to a byte-identical comic download | FRG-OPDS-001, FRG-OPDS-002, FRG-OPDS-003, FRG-OPDS-005, FRG-PROC-010 |
| SKIPPED | FRG-PROC-010: live SABnzbd tier (skipped — no credentials) | FRG-PROC-010 |
| PASS | FRG-PROC-010 FRG-UI-015 FRG-IMP-022 FRG-IMP-023: library import scans a root, reviews matches and imports existing files in place without a download | FRG-IMP-022, FRG-IMP-023, FRG-PROC-010, FRG-UI-015 |
| PASS | FRG-PROC-010 FRG-API-011: History shows the grabbed and imported rows sharing a downloadId | FRG-API-011, FRG-PROC-010 |
| PASS | FRG-PROC-010 FRG-API-012: Wanted lists a monitored, published, fileless issue | FRG-API-012, FRG-PROC-010 |
| PASS | FRG-PROC-010 FRG-OPDS-013: OPDS Recent serves the imported issue file bytes | FRG-OPDS-013, FRG-PROC-010 |
| PASS | FRG-PROC-010 FRG-SCHED-002: library and command queue survive a container restart | FRG-PROC-010, FRG-SCHED-002 |
| PASS | FRG-PROC-010 FRG-UI-005: an unconfigured ComicVine key surfaces an actionable credential error, not "no results" | FRG-PROC-010, FRG-UI-005 |

## Requirement roll-up

| FRG id | Result |
| --- | --- |
| FRG-API-011 | PASS |
| FRG-API-012 | PASS |
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
| FRG-PP-009 | PASS |
| FRG-PP-010 | PASS |
| FRG-PROC-010 | PASS |
| FRG-SCHED-002 | PASS |
| FRG-SER-005 | PASS |
| FRG-SER-009 | PASS |
| FRG-SRCH-001 | PASS |
| FRG-UI-003 | PASS |
| FRG-UI-005 | PASS |
| FRG-UI-007 | PASS |
| FRG-UI-008 | PASS |
| FRG-UI-015 | PASS |

---

_Hermetic-fixture coverage has known limits: this run does NOT exercise multi-host DDL landing-page parsing/failover, real redirect chains, or real SABnzbd unless the live tier runs. See the **Coverage limits** section of `e2e/README.md` before over-reading this report._
