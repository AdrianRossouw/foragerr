# Change: Establish the full requirements baseline

## Why

Per the approved Phase 2 plan: foragerr specs the entire system mined from Mylar3 and
Sonarr up front — full breadth at controlled depth — so milestones implement traceable
subsets of an owner-approved baseline, and so the threat analysis can see the whole
system (including deferred capabilities) rather than a slice.

## What Changes

- 270 baseline requirements across 20 new capability specs (`openspec/specs/<area>/`):
  SER, META, PULL, ARC, IDX, SRCH, DL, DDL, TOR, IMP, PP, API, UI, OPDS, NOTIF, DB,
  SCHED, DEP, AUTH, NFR — each `### Requirement: FRG-<AREA>-<NNN> — <name>` with a
  SHALL statement, source citation into `docs/research/`, milestone tag, and one coarse
  acceptance scenario. Scenario-level elaboration is deferred to milestone changes
  (FRG-PROC-003/009). One requirement (FRG-PP-015) was withdrawn during synthesis as a
  duplicate of FRG-DL-011/012/013 + FRG-PP-006.
- Registry regenerated with Status and Milestone columns; all baseline rows `proposed`
  until owner approval flips them to `approved`. Milestones: M1 vertical slice,
  M2 torrents + OPDS-PSE/quality clusters, M3 authentication, B backlog.
  (Pre-existing FRG-PROC rows keep their `active` status: the process area predates
  this vocabulary and its tooling-enforcement story is revisited when tests exist.)
- `tools/trace.py`: regenerates `docs/traceability/matrix.md` from registry + spec
  headings + commit `Refs:` trailers + test tags; exits non-zero on inconsistencies
  (FRG-PROC-005).
- Security artifacts (`docs/security/threat-model.md`, `docs/security/risk-register.md`)
  and SEC-area requirements from the system-wide STRIDE analysis (FRG-PROC-006).

## Non-goals

- No product code and no tests (beyond trace tooling); implementation starts in
  Phase 3 against approved milestone changes.
- READ area (in-browser reader, tablet SFTP sync, reading lists) is permanently out of
  scope — foragerr reads via OPDS clients only.
- Deliberate exclusions with rationale, collected from the drafting pass (full list in
  `openspec/changes/establish-requirements-baseline/exclusions.md`): Mylar one-off
  downloads and publisher auto-mass-add; ComicTagger subprocess tagging (native
  in-process instead); series.json/cvinfo sidecars; legacy GCD/ComicBookDB scrapers;
  nzbindex "experimental" scraper; NZBGet; blackhole + external post-process scripts
  and shell hooks; SABnzbd add-by-URL; Mylar rssdb offline matching; DDL(External)
  server; 32P and per-site public-tracker scrapers; seedbox SFTP harvester and
  watch-dir torrent clients (torrents arrive M2 via Torznab + qBittorrent only);
  git self-update.

## Impact

- Affected specs: 20 new capability specs + registry + traceability tooling.
- Affected code: none yet (spec-only change).

## Approval

_Pending owner review (FRG-PROC-009). This change is not archived and the registry
rows stay `proposed` until approval is recorded here._
