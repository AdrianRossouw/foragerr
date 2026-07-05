# Change: Manual, labelling, and SOUP register kept in sync with the application

## Why

foragerr is a working demonstration of regulated software development. In a regulated
environment, user-facing documentation is a controlled artifact: a manual that drifts
from the application it describes is an audit finding (in medical-device terms, an
IFU/labelling-control failure), and third-party software is tracked as SOUP (Software
of Unknown Provenance, IEC 62304) in a maintained register. The project currently has
strong requirement/test/commit traceability but **no manual, no README/labelling, and
no SOUP register**, and no rule forcing any of them to stay current. Adrian requested
this on 2026-07-05: "manual needs to be kept in sync with application", README as
labelling/technical documentation, and a maintained SOUP document.

## What Changes

- **FRG-PROC-011 — Manual kept in sync with the application.** The project maintains a
  user and administrator manual in `docs/manual/`, plus the repository `README.md` as
  top-level labelling/technical documentation (what the project is, its security and
  regulatory posture, the way of working, and — once the deployment surface exists
  after change 7 — installation). Every OpenSpec change proposal declares its manual
  impact (sections added/updated, or an explicit "no manual impact" with rationale); a
  change that alters manual-documented behavior updates the affected sections **in the
  same change**, before merge to `main`; the merge gate verifies the declared impact
  was carried out.
- **FRG-PROC-012 — SOUP register.** `docs/security/soup-register.md` lists every direct
  third-party runtime dependency (backend + frontend) with version constraint, source,
  intended purpose, supporting requirements, license, and a known-anomaly review note;
  dev/test tooling is listed in a lighter tools section. Any change that adds, removes,
  or upgrades a dependency updates the register in the same change. A mechanical check
  (`tools/soup_check.py`, beside `trace.py`) verifies register-vs-manifest consistency
  and must exit 0 at every merge gate.
- **Initial backfill.** Created as part of this change's implementation, covering what
  is already merged to `main` at backfill time: user guide (library, metadata,
  search/indexers, downloads, import), admin guide (deployment, configuration/
  `FORAGERR_*` env, port, Docker conventions), `README.md` (posture + way of working;
  installation deferred until after change 7), and the SOUP register backfilled from
  current `pyproject.toml` / `package.json`.
- **Process wiring.** `CLAUDE.md` process rules and `docs/process/` gain the
  manual-impact declaration + gate checks; `docs/process/decisions.md` indexed.

## Non-goals

- No in-app help, generated docs site, or published/versioned manual — a single rolling
  Markdown manual in-repo, matching `main`, is the controlled artifact.
- No screenshot pipeline; screenshots may be added after the UI exists (change 7), but
  are not required for currency.
- No retroactive manual-impact sections in already-approved M1 proposals (changes 6–8):
  their user-facing behavior is captured by the backfill; the declaration requirement
  binds proposals authored after this change is approved.
- No automated prose-vs-code verification for the manual — that gate check is a
  human/agent review step, like the FRG-PROC-006 security-docs check it mirrors (the
  SOUP check, by contrast, IS mechanical).
- No per-item transitive-tree anomaly review — the SOUP register covers **direct**
  dependencies; lockfiles (`uv.lock`, `package-lock.json`) remain the authoritative
  pin of the full tree.
- No automated CVE-scanning service — the known-anomaly review is a manual
  changelog/advisory check recorded (with date) when an item is added or upgraded.
- README installation section deferred until the deployment surface exists (after
  change 7); a placeholder pointing at the admin guide is acceptable until then.

## Impact

- Affected specs: `dev-process` (two added requirements)
- Affected code/docs: `docs/manual/` (new), `README.md` (new),
  `docs/security/soup-register.md` (new), `tools/soup_check.py` (new), `CLAUDE.md`,
  `docs/process/commit-standard.md` (gate checklist), `docs/process/decisions.md`,
  `docs/traceability/requirements-registry.md` (FRG-PROC-011/012 rows)

## Approval

- Pending owner approval (FRG-PROC-009).
