# Change: Manual kept in sync with the application

## Why

foragerr is a working demonstration of regulated software development. In a regulated
environment, user-facing documentation is a controlled artifact: a manual that drifts
from the application it describes is an audit finding (in medical-device terms, an
IFU/labelling-control failure). The project currently has strong requirement/test/commit
traceability but **no user or administrator manual at all**, and no rule forcing one to
stay current. Adrian requested this on 2026-07-05: "manual needs to be kept in sync
with application."

## What Changes

- **FRG-PROC-011 — Manual kept in sync with the application.** The project maintains a
  user and administrator manual in `docs/manual/`. Every OpenSpec change proposal
  declares its manual impact (sections added/updated, or an explicit "no manual impact"
  with rationale); a change that alters manual-documented behavior updates the affected
  sections **in the same change**, before merge to `main`; the merge gate verifies the
  declared impact was carried out.
- **Initial backfill.** The manual is created as part of this change's implementation,
  covering behavior already merged to `main` at backfill time (M1 changes landed so
  far): user guide (library, metadata, search/indexers, downloads, import) and admin
  guide (deployment, configuration/`FORAGERR_*` env, port, Docker conventions).
- **Process wiring.** `CLAUDE.md` process rules and `docs/process/` gain the
  manual-impact declaration + gate check; `docs/process/decisions.md` indexed.

## Non-goals

- No in-app help, generated docs site, or published/versioned manual — a single rolling
  Markdown manual in-repo, matching `main`, is the controlled artifact.
- No screenshot pipeline; screenshots may be added after the UI exists (change 7), but
  are not required for currency.
- No retroactive manual-impact sections in already-approved M1 proposals (changes 6–8):
  their user-facing behavior is captured by the backfill; the declaration requirement
  binds proposals authored after this change is approved.
- No automated prose-vs-code verification — the gate check is a human/agent review
  step, like the FRG-PROC-006 security-docs check it mirrors.

## Impact

- Affected specs: `dev-process` (one added requirement)
- Affected code/docs: `docs/manual/` (new), `CLAUDE.md`,
  `docs/process/commit-standard.md` (gate checklist), `docs/process/decisions.md`,
  `docs/traceability/requirements-registry.md` (FRG-PROC-011 row)

## Approval

- Pending owner approval (FRG-PROC-009).
