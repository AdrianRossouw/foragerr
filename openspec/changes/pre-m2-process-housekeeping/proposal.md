# Change: Pre-M2 process housekeeping — release tagging, SOUP-anomaly defer, quality park

## Why

Three owner decisions from the 2026-07-06 planning session need process homes before
M2 work begins, and one of them (release tagging) must exist as a requirement before
the first tag is created at change 7's merge:

1. **Release tagging (Adrian, 2026-07-06):** tag releases with SemVer so a previous
   release can be restored if the development environment or credits are lost. Tags
   are restore points; they must be pushed to origin to survive sandbox loss.
2. **SOUP anomaly review is training-data-derived (Adrian, 2026-07-06):** the
   per-item "known vulnerabilities as of <date>" cells in
   `docs/security/soup-register.md` were written from the reviewing agent's training
   knowledge, not a live advisory query — not useful, and they create a false sense
   of security-review rigor. An audit-credible register keeps the honest inventory
   and defers systematic anomaly review to real tooling.
3. **Quality trio parked (Adrian, 2026-07-06):** FRG-QUAL-003/004/005 (preferred-term
   scoring, per-profile size bounds, profile management UI) move from M2 to backlog B
   — comic files are size-stable; upgrade-to-bigger-file churn is a video-world
   concern with marginal payoff for comics. The useful library-hygiene parts are
   re-homed instead: FRG-PP-013 (recycle bin) into M2's settings/naming change,
   FRG-PP-014 (duplicate handling) into M2's existing-library-import change, and
   API-012's "cutoff-unmet" surface simplifies to plain wanted/missing in M2's
   daily-surfaces change.

## What Changes

- **FRG-PROC-013 — Release tagging (ADDED).** Every change merged to `main` from
  change 7 (`m1-ui-opds-deploy`) onward gets an annotated SemVer tag on its merge
  commit: milestone completion sets the MINOR line (M1 = 0.1, M2 = 0.2, M3 = 0.3),
  each subsequent merged change within a milestone increments PATCH. v0.1.0 =
  change 7 (M1 feature-complete); v0.1.1 = change 8 (M1 acceptance-certified — a
  patch bump, not an RC relabel, because integration testing produces real
  functional deltas). Tag messages carry the change id and FRG refs; tags (and
  `main`) are pushed to origin at tag time so restore points survive environment
  loss.
- **FRG-PROC-012 — SOUP register (MODIFIED).** The known-anomaly-review column is
  replaced by a deferred-methodology posture: the register remains the authoritative
  **inventory** (name, version constraint, source, purpose, supporting requirements,
  license) with the mechanical `soup_check.py` drift gate, while systematic
  anomaly/vulnerability review is recorded as a **documented future improvement**
  pending network-connected CI (`pip-audit` / `npm audit` / Dependabot). Existing
  training-data-derived anomaly cells are replaced with "Deferred — see
  methodology"; the methodology note states why and what replaces it.
- **Registry milestone moves (no spec-content change):** FRG-QUAL-003/004/005
  `M2 → B`. Their requirement text stays in the `qual` baseline spec unchanged;
  only scheduling moves. `docs/process/decisions.md` records the rationale and the
  re-homing knock-ons (PP-013, PP-014, API-012) so M2 proposals cite it.
- **Merge-gate checklist** in `docs/process/commit-standard.md` gains the tagging
  step (from change 7 onward).

## Non-goals

- No retroactive tags for changes 1–6 (pre-M1-completion merges are not restore
  targets; the scheme starts where Adrian asked, at change 7).
- No automated CVE-scanning service in this change — that is exactly what is being
  deferred until network-connected CI exists; this change makes the deferral honest
  and documented rather than silently fabricated.
- No removal of FRG-QUAL-003/004/005 from the `qual` spec — parked, not withdrawn.
- No frontend SOUP rows — `frontend/package.json` still does not exist on `main`
  (that lands with change 7, which adds its rows per the existing scenario).

## Impact

- Affected specs: `dev-process` (one added requirement FRG-PROC-013, one modified
  FRG-PROC-012)
- Affected docs: `docs/security/soup-register.md` (methodology + anomaly cells),
  `docs/process/commit-standard.md` (gate checklist), `docs/process/decisions.md`
  (two decision records), `docs/traceability/requirements-registry.md`
  (FRG-PROC-013 row; QUAL-003/004/005 milestone cells)
- No production code. No dependency changes.

## Manual impact

None. This change is development-process-only: tagging, SOUP-register methodology,
and milestone scheduling are not user- or administrator-facing application behavior.
(`docs/manual/` documents the application; the process docs live in
`docs/process/`.) Release tags will become user-visible once releases are published,
which is itself a non-goal of the project.

## Approval

- **Approver:** Adrian
- **Date:** 2026-07-06
- **Decision:** Approved under the M2/M3 standing grant of 2026-07-06 ("keep going
  with m2/m3 and all their related changes as you go. I'll come check in later"),
  which the run-order plan places immediately after change 6 so FRG-PROC-013 exists
  before the first tag at change 7. All three bundled decisions were made explicitly
  by Adrian in the 2026-07-06 planning session.
