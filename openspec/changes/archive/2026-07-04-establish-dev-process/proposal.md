# Change: Establish the regulated development process

## Why

foragerr is both a product (a Sonarr-style comic manager replacing Mylar) and a
demonstration of regulated software development. Before any product code exists, the
process itself must be specified, given requirement IDs, and enforced by tooling —
otherwise nothing that follows can be traced.

## What Changes

- Define the `dev-process` capability with requirements FRG-PROC-001..006: commit
  traceability, stable requirement IDs, spec-before-code, test tagging, a traceability
  matrix, and a threat-analysis/risk-register obligation.
- Create the requirements registry at `docs/traceability/requirements-registry.md`.
- Document the commit standard at `docs/process/commit-standard.md`.
- Install an enforcing `commit-msg` hook at `.githooks/commit-msg` and point
  `core.hooksPath` at it.
- Initialize OpenSpec (this structure) as the spec framework, extended per the above.

## Non-goals

- No product requirements are defined here; those arrive in per-capability changes
  after the Mylar3/Sonarr reference-mining phase.
- CI enforcement (server-side re-validation of hooks, matrix regeneration) is deferred
  until a CI pipeline exists; the obligations are still stated in the requirements.

## Impact

- Affected specs: `dev-process` (new)
- Affected code: repository scaffolding only (`.githooks/`, `docs/`, `openspec/`, `CLAUDE.md`)
