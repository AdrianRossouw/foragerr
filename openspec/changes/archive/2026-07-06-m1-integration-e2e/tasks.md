# Tasks

## 1. Registry and conventions

- [x] 1.1 Allocate FRG-PROC-010 in docs/traceability/requirements-registry.md (proposed, milestone M1) (FRG-PROC-002)
- [x] 1.2 `e2e/SELECTORS.md`: ft-* data-testid conventions for change 7's frontend (FRG-PROC-010)

## 2. Harness

- [x] 2.1 `e2e/` Playwright TS package: config (trace/screenshot on failure, retries=1), single entrypoint wrapping compose lifecycle (FRG-PROC-010)
- [x] 2.2 `e2e/compose.yaml`: foragerr image + fixture-cv + fixture-indexer + fixture-ddl (+ profile-gated real sabnzbd with .env news servers); ephemeral ports; egress profiles configured for the compose network (FRG-PROC-010)
- [x] 2.3 Fixture services: recorded CV responses, rejection-rich Newznab set, GetComics pages + downloadable test archive (FRG-PROC-010)

## 3. Scenario spine

- [x] 3.1 S1 first-run health/config/profile seed; S2 add series; S3 interactive search rejection reasons (FRG-PROC-010)
- [x] 3.2 S4 grab→queue→import→renamed file; S5 UI browse; S6 OPDS navigation + MIME/byte-identical download (FRG-PROC-010)
- [x] 3.3 S7 live-SAB tier (profile-gated, one small NZB); S8 restart resilience mid-queue (FRG-PROC-010)
- [x] 3.4 `backend/tests/test_e2e_marker.py`: manifest-coverage test tagged FRG-PROC-010 (FRG-PROC-004)

## 4. Gate

- [x] 4.1 Green hermetic run against the change-7 image; run log attached to the M1 review packet; registry flip; trace.py; merge --no-ff; archive (FRG-PROC-005, FRG-PROC-007, FRG-PROC-010)
