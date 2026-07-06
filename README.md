# foragerr

A private, Sonarr-style comic management tool replacing Mylar: library import and
renaming, ComicVine metadata, Newznab indexers (DogNZB, NZB.su), SABnzbd and
built-in direct-download (DDL) acquisition, and (planned) an OPDS server for iPad
reading over Tailscale. There is no built-in reader.

foragerr is **not released publicly** — it runs on one owner's home server for
personal use. It doubles as a working demonstration of regulated software
development practice applied to a small, real project (see the formicary.ai
context this project is developed under).

This file is foragerr's top-level labelling and technical documentation: what the
project is, how it is developed and secured, and where to find more detail. For
day-to-day usage and configuration, see the [manual](docs/manual/index.md).

## Stack

- **Backend**: Python (FastAPI), SQLite.
- **Frontend**: React + TypeScript (not yet built — see Installation below).
- **Deployment target**: Docker on a home server, linuxserver.io image conventions
  (not yet packaged — see Installation below).

## Security & regulatory posture

foragerr is developed under a written development-process specification
(`openspec/specs/dev-process/spec.md`) that treats several things a regulated
software project would treat as controlled artifacts:

- **Spec before code.** No production code is written without a governing OpenSpec
  change proposal containing the requirements it implements, approved by the
  project owner before implementation begins.
- **Requirement traceability.** Every requirement has a stable, never-reused ID
  (`FRG-<AREA>-<NNN>`, registered in
  `docs/traceability/requirements-registry.md`) and at least one test tagged with
  that ID. The traceability matrix (`docs/traceability/matrix.md`) is regenerable
  from the registry, test tags, and commit trailers — not hand-maintained.
- **Threat modelling and a risk register.** New attack surface (a listener, a parser
  of untrusted input, credentials, an outbound integration) requires an update to
  `docs/security/threat-model.md` (STRIDE analysis) and `docs/security/risk-register.md`
  in the same change that introduces it. Accepted risks (for example, foragerr
  currently shipping with no application authentication — see
  `docs/manual/admin/network.md`) are recorded there with an owner, a rationale, and
  a review trigger, not silently deferred.
- **A SOUP register.** Third-party runtime dependencies are tracked as SOUP
  (Software of Unknown Provenance, in IEC 62304 terms) in
  `docs/security/soup-register.md`: version constraint, source, purpose, and
  license per dependency, kept in sync whenever a dependency is added, removed,
  or upgraded. Systematic anomaly/vulnerability review is deferred until
  network-connected CI exists (see the register's methodology note).
- **A manual kept in sync with the application.** `docs/manual/` is a controlled
  artifact: a change that alters documented behavior updates the affected manual
  section in the same change, before merge — see `docs/manual/index.md`'s currency
  statement for exactly what is covered as of today.

## Way of working

- **Specs are the source of truth.** `openspec/specs/` holds the baseline
  requirements per capability area; `openspec/changes/` holds in-flight change
  proposals (design + spec deltas + tasks) until they are implemented and archived
  back into the baseline.
- **Commits are traceable.** Every commit uses Conventional Commits format plus a
  mandatory `Refs: FRG-...` trailer citing the requirement IDs it touches, enforced
  by a commit-msg hook (`docs/process/commit-standard.md`).
- **Branches only; `main` stays green.** Nobody commits directly on `main`. Work
  happens on `change/<id>`, `research/<topic>`, or `process/<name>` branches and
  lands via `git merge --no-ff` only while the full test suite passes.
- **Spec approval gate.** Every OpenSpec proposal is explicitly approved by the
  project owner (recorded in the proposal's `## Approval` section) before any
  implementation work starts.

See `CLAUDE.md` and `docs/process/` for the full set of process rules and how they
are enforced.

## Installation

foragerr does not yet have a packaged install path — the Docker image and
deployment tooling are being built under OpenSpec change `m1-ui-opds-deploy` and
have not merged yet. Until then:

- See `docs/manual/admin/` for configuration, secrets handling, and the
  Tailscale-only network posture that applies regardless of how you run the
  application.
- See `docs/manual/admin/deployment.md` for the packaging design that is committed
  in spec but not yet implemented.

Full installation instructions will replace this section once the deployment
change lands.
