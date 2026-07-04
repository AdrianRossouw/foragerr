# Change: m1-library-metadata — ComicVine client and the library domain

## Why

Phase 3 change 3 of 7 (approved plan, 2026-07-04). With the platform backbone
(change 1) and the parser (change 2) in place, this change makes foragerr *about
comics*: the series/issue domain model, the ComicVine client that populates it, and
the first real API surface. Everything downstream (search, downloads, import, UI,
OPDS) operates on the entities and flows established here.

## What Changes

Implements 28 approved baseline requirements (no new IDs; scenario elaboration only):

- **Library domain (FRG-SER-001..009, 014)** — series entity keyed by ComicVine
  volume ID with a format-profile reference; issue entities with decimal/suffix-safe
  numbers; two-level monitored flags (series AND issue); wanted as a *derived*
  predicate, never stored; the add flow as a chained command sequence
  (add → refresh → scan → optional search) on the SCHED backbone; add-time monitoring
  strategies and monitor-new-items policy; root folders + templated series paths;
  derived statistics; series edit and safe delete. Disk scan matches files to issues
  via the change-2 parser; routing *unmatched* files into the shared import pipeline
  is change 6 (FRG-SER-010 claimed there).
- **ComicVine client (FRG-META-001..008, 013, 014)** — JSON-only client on the shared
  HTTP factory (`external` profile): honest UA, mandatory timeouts, TLS on; redacted
  API-key handling; process-global rate limiter (default 1 req/2s) honoring
  Retry-After with degraded-health signalling; offset pagination that persists
  partial results and records incompleteness; volume→series and issue→issue mapping
  as typed nullable values (no sentinels); series search with plausibility annotations
  and publisher ignore-list; refresh reconciliation on the Sonarr model
  (insert/update/delete by CV issue ID, **no deletes on partial fetch**); cover art
  download/cache under `/config` serving all artwork locally; every ComicVine string
  treated as untrusted input (sanitize on ingest, encode on output).
- **Format profiles (FRG-QUAL-001, 002)** — profile entity (ordered container formats
  + cutoff) and the seeded default (`pdf < cbr < cbz`, cutoff `cbz`) auto-assigned to
  new series, giving changes 4-6 a concrete profile to evaluate against.
- **Cross-cutting (FRG-NFR-004, 012)** — the shared CV rate limiter as the single
  choke point for all ComicVine traffic; untrusted-external-content discipline
  (HTML-strip on ingest, no raw CV text into paths/queries/logs).
- **API (FRG-API-003..006)** — series resources with `/series/lookup` (live CV
  search), issue resources with bulk monitored toggle, the `POST /command` endpoint
  formalized over the change-1 backbone, and the paging envelope applied to the
  series/issue list endpoints.

## Capabilities

### New Capabilities

None — all requirements exist in the approved baseline specs.

### Modified Capabilities

Delta specs elaborate M1 acceptance scenarios:

- `ser`: FRG-SER-001..009, 014
- `meta`: FRG-META-001..008, 013, 014
- `qual`: FRG-QUAL-001, 002
- `nfr`: FRG-NFR-004, 012
- `api`: FRG-API-003, 004, 005, 006

## Non-goals

- No unmatched-file import routing (FRG-SER-010, change 6) and no library-import
  staging (M2). Scan in this change matches existing files to known issues and
  records unmatched paths for later.
- No scheduled/incremental refresh (FRG-META-009/010, B), no volume identity-change
  guard (FRG-META-011, B), no heuristic provenance overrides (FRG-META-012, B).
- No search integration beyond enqueueing a search command stub for the add flow's
  optional search step (the real handler arrives in change 4).
- No annuals/specials issue typing (FRG-SER-011, B), no status maintenance
  (FRG-SER-012, B), no override-survival (FRG-SER-013, B), no bulk ops (FRG-SER-015, B).
- No UI (change 7); interaction is via the API only.

## Impact

- **New code**: `backend/src/foragerr/{library/, metadata/, quality/}` + API routers
  under `backend/src/foragerr/api/`; Alembic migrations for series/issues/root-folder/
  profile tables; tests under `backend/tests/`.
- **Dependencies**: no new runtime deps (httpx via the change-1 factory; SQLAlchemy
  models on the change-1 base).
- **External services**: ComicVine — fixture-recorded responses for the suite; live
  smoke behind an env-gated marker using the `.env` key (never logged or committed).
- **Security**: outbound integration (ComicVine) rides the existing SSRF/egress
  choke point; CV content-handling risks RISK-011/RISK-014/RISK-019 (untrusted wiki
  HTML, unescaped scraped text, CV titles in paths) get their mitigation status
  updated in `docs/security/risk-register.md` in this change (FRG-PROC-006).
- **Registry**: on merge, the 28 rows flip `approved → implemented`.

## Approval

- **Approver:** Adrian
- **Date:** 2026-07-04
- **Decision:** Approved under the standing grant of 2026-07-04 covering changes 3-7
  ("assume my approval for the rest of the changes up through 7, and i'll review
  after they are complete"). Implementation may begin, scoped to the 28 requirements
  listed above.
