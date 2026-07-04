# Change: Branch-based integration, worktree isolation, and spec approval gates

## Why

Multiple agents will work concurrently on this repository, and the requirements
baseline will be implemented incrementally across milestones. Without explicit rules,
concurrent agents can trample each other's working tree, `main` accumulates
work-in-progress commits, and specs can drift into implementation without the owner
ever agreeing to them. Adrian requested all three protections on 2026-07-04.

## What Changes

- **FRG-PROC-007 — Branch-based integration, green main.** No direct commits to
  `main`; all work lands via `--no-ff` merges from branches (`change/<id>`,
  `research/<topic>`, `process/<name>`), only while the full test suite passes.
  The Phase 0 bootstrap root commit (6401930) predates this rule and is grandfathered.
  CI re-enforcement is an obligation deferred until a CI pipeline exists.
- **FRG-PROC-008 — Worktree isolation for concurrent agents.** File-mutating agents
  each work in their own git worktree on their own branch; research agents are
  read-only and return findings as text; the orchestrator owns writes, merges, and
  worktree cleanup.
- **FRG-PROC-009 — Spec approval gate.** No implementation of an OpenSpec change until
  Adrian approves the proposal, recorded in an `## Approval` section. Phase
  transitions additionally pass through plan-mode gates.

Enforcement: a new `.githooks/pre-commit` rejects commits made directly on `main`
unless a merge is in progress.

## Non-goals

- No CI pipeline yet (the green-main check is executed manually until one exists).
- No server-side branch protection (single-user local repo; hooks + process suffice).
- No change to the commit message standard itself (FRG-PROC-001 is unchanged).

## Impact

- Affected specs: `dev-process` (three added requirements)
- Affected code: `.githooks/pre-commit` (new), `CLAUDE.md`,
  `docs/process/commit-standard.md`, `docs/traceability/requirements-registry.md`

## Approval

- **Approver:** Adrian
- **Date:** 2026-07-04
- **Decision:** Approved via plan-mode gate — plan "Collaboration process amendments +
  Phase 1 reference mining" accepted, which explicitly stated that plan approval
  constitutes the FRG-PROC-009 approval for this change.
