# foragerr

A private, Sonarr-style comic management tool replacing Mylar: library import/renaming,
ComicVine metadata, Newznab indexers (DogNZB, NZB.su), SABnzbd + built-in DDL
downloading, and an OPDS server for iPad reading over Tailscale. No built-in reader.
Never released publicly — it is also a working demonstration of regulated software
development (see https://formicary.ai context).

**Stack**: Python backend (FastAPI), React + TypeScript frontend, SQLite.
**Deployment target**: Docker on a home server, linuxserver.io image conventions.

## Non-negotiable process rules

This project is developed under the `dev-process` spec
(`openspec/specs/dev-process/spec.md`, FRG-PROC-001..006). In practice:

1. **Spec before code** (FRG-PROC-003). Never write production code without an OpenSpec
   change proposal containing the governing requirements. Use the `opsx` commands/skills
   installed in `.claude/`.
2. **Requirement IDs** (FRG-PROC-002). Every requirement is `FRG-<AREA>-<NNN>`,
   allocated in `docs/traceability/requirements-registry.md` at proposal time. Never
   reuse or renumber an ID. AREA table lives in `docs/process/commit-standard.md`.
3. **Commit format** (FRG-PROC-001). Conventional Commits subject + mandatory
   `Refs: FRG-...` trailer citing registered IDs. Enforced by `.githooks/commit-msg`
   (`core.hooksPath` is set to `.githooks`; re-run
   `git config core.hooksPath .githooks` after a fresh clone).
4. **Tests are traceable** (FRG-PROC-004). Every requirement gets at least one test
   tagged with its ID — pytest: `@pytest.mark.req("FRG-IMP-003")`; vitest: include the
   ID in the test name. A requirement without a passing tagged test is not done.
5. **Traceability matrix** (FRG-PROC-005) lives in `docs/traceability/` and must be
   regenerable from registry + test tags + commit trailers.
6. **Security is spec'd** (FRG-PROC-006). New attack surface (listener, parser of
   untrusted input, credentials, outbound integration) requires updating
   `docs/security/` (STRIDE analysis + risk register) in the same change.

## Orchestration

The main session acts as orchestrator. Fan implementation and research work out to
sub-agents scoped to specific requirement IDs (one worker per requirement or small
cluster), and have them report back against those IDs. Keep expensive exploration in
sub-agents, synthesis and decisions in the orchestrator.

## Layout

- `openspec/` — specs (source of truth) and change proposals
- `docs/process/` — commit standard and process docs
- `docs/traceability/` — requirements registry, traceability matrix
- `docs/security/` — threat analysis, risk register
- `docs/research/` — findings mined from Mylar3/Sonarr reference code
- `.reference/` — gitignored clones of Mylar3/Sonarr for study; never import code from
  here wholesale, and never commit it
- `backend/`, `frontend/` — product code (created in the vertical-slice milestone)

## Secrets

API keys (ComicVine, DogNZB, NZB.su, SABnzbd) come from environment variables /
`.env` (gitignored). Never hardcode or commit keys, and never echo them into files,
logs, or commit messages.
