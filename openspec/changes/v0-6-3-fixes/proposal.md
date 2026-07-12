# v0-6-3-fixes

## Why

The first live SABnzbd exercise (2026-07-12, real DogNZB + Newshosting via a
sandboxed SABnzbd 5.0.4) proved the whole usenet chain works — search, grab
command, client add, NNTP download, tracking, import — except for one released
bug that has silently broken every real grab since M1: `_validate_nzb` parses
fetched NZB bytes with the project-wide hardened XML parser (`forbid_dtd=True`),
but the NZB 1.1 format specification *mandates* a
`<!DOCTYPE nzb PUBLIC "-//newzBin//DTD NZB 1.1//EN" ...>` header. Every
spec-conformant NZB from a real indexer therefore raises `DTDForbidden` and the
grab fails before SABnzbd ever sees it. The hermetic e2e fixtures omit the
DOCTYPE, so all suites stay green — a fixtures-must-mirror-reality failure of
exactly the kind the CV person_credits lesson warned about.

Two small owner-triaged items ride along (owner instruction 2026-07-12: no
dedicated review-fixes release; ride a v0.6.x change): deterministic
traceability-matrix regeneration, and a refreshed README Sources screenshot
captured from a real connected account (owner-requested, using his own
Humble session).

## What Changes

1. **NZB parsing tolerates the spec-mandated DOCTYPE — nothing else** (bug fix).
   A dedicated NZB parse entry point accepts a DTD *declaration* while keeping
   every dangerous property forbidden: entity declarations rejected
   (billion-laughs/quadratic blowup), external entity resolution disabled (XXE),
   byte cap unchanged. All other XML surfaces (Newznab caps/RSS, future CBL)
   keep full `forbid_dtd=True`. FRG-SEC-002's blanket wording is amended to
   state the NZB-path carve-out precisely; FRG-DL-003 gains a scenario pinning
   that a spec-conformant NZB is accepted and an entity-bearing NZB is not.
   Threat model updated in the same change (FRG-PROC-006).
2. **Deterministic matrix regeneration** (housekeeping, FRG-PROC-005): test-file
   lists inside matrix cells are emitted sorted, so regeneration is stable
   run-to-run instead of reshuffling (noise in diffs at every gate).
3. **README Sources screenshot from a real connected account** (docs): the
   capture script's `sources` step gains a connected-state branch — when the
   target instance has a connected source it shoots the review queue
   (StoreManage) instead of the connect card — and `docs/readme-assets/
   sources.png` is refreshed from the operator's real account (owner-requested
   2026-07-12; supersedes the unconfigured-only capture note). The cookie is
   never visible in any UI state; the shot shows entitlement titles the owner
   chose to publish.

Version: v0.6.3 (CHANGELOG entry + `backend/pyproject.toml` bump in-change,
FRG-PROC-013).

Out of scope: the cover-WS-push fix from the owner's queue already landed in
v0.6.0 (FRG-META-013 amendment, `refresh.py` queues `SeriesRefreshed` in the
cover-stamp transaction); the live-SABnzbd e2e tier body (`E2E_LIVE_SAB`)
stays a gated stub — the fix is verified live against the standing rig instead
(UAT, mirroring the Humble A1 approach).

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `sec`: FRG-SEC-002 amended — hardened-XML rule gains a precise NZB-path
  carve-out: an inert DOCTYPE declaration is tolerated on NZB payloads only;
  entity declarations, external resolution, and unbounded expansion remain
  forbidden everywhere, and every non-NZB surface keeps DOCTYPE processing
  fully disabled.
- `dl`: FRG-DL-003 scenario updated — NZB validation accepts spec-conformant
  (DOCTYPE-bearing) NZBs; rejection cases now explicitly include
  entity-declaration payloads alongside empty/non-XML/segmentless bytes.

## Impact

- `backend/src/foragerr/indexers/xml.py` — new `parse_nzb_xml` (or parameterized
  entry point) beside `parse_indexer_xml`; module docstring updated.
- `backend/src/foragerr/downloads/clients/sabnzbd.py` — `_validate_nzb` uses the
  NZB parse.
- `tools/trace.py` — sorted cell emission; `docs/traceability/matrix.md`
  regenerated once (the diff shows the one-time reordering).
- `e2e/scripts/capture-readme-shots.ts` — connected-state sources branch;
  `docs/readme-assets/sources.png` refreshed; README untouched otherwise.
- `docs/security/threat-model.md` — FRG-SEC-002 note (RISK-024/035/037
  unaffected: the forbidden properties that mitigate them are retained).
- Tests: real-DOCTYPE NZB fixture accepted (FRG-DL-003); entity-bearing NZB
  rejected (FRG-SEC-002); matrix determinism pin (FRG-PROC-005).
- Manual impact: **none** (no user/admin-facing behavior change; README
  screenshot refresh is labelling-neutral) — rationale per FRG-PROC-011.
- No dependency changes (SOUP register untouched; `soup_check` must still
  exit 0).

## Approval

Covered by the owner's standing grant, 2026-07-12 (recorded in session memory
`m8-standing-grant`): "you don't need my approval for bugfixes like that. keep
on going with approved development until you get to the UI improvement
milestone." The screenshot item is additionally an explicit owner request from
the same session ("is it possible to use my humble test cookie to take the
humble importer screenshot").
