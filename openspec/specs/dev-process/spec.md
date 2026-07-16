# dev-process Specification

## Purpose

foragerr is built as a demonstration of regulated software development practice. This
capability governs *how* the project is developed: requirement identity, traceability
from requirements to specs, tests, and commits, and security risk management. These
requirements apply to every contributor — human or agent — and are enforced by
tooling wherever possible.
## Requirements
### Requirement: FRG-PROC-001 — Commit traceability

Every commit on any branch SHALL follow the Conventional Commits format and SHALL carry
a `Refs:` trailer listing at least one registered requirement ID that the commit
implements, tests, or documents. Merge and revert commits are exempt. Enforcement SHALL
be automated via a `commit-msg` hook.

#### Scenario: Compliant commit accepted

- **WHEN** a commit message has a valid Conventional Commits subject and a `Refs:` trailer citing IDs present in the requirements registry
- **THEN** the commit-msg hook accepts the commit

#### Scenario: Missing or unknown requirement reference rejected

- **WHEN** a commit message lacks a `Refs:` trailer, or cites an ID absent from the requirements registry
- **THEN** the commit-msg hook rejects the commit with an explanation of the required format

### Requirement: FRG-PROC-002 — Stable requirement identifiers

Every requirement SHALL have a unique identifier of the form `FRG-<AREA>-<NNN>`,
allocated in `docs/traceability/requirements-registry.md` when the requirement is first
proposed. Identifiers SHALL never be reused or renumbered; withdrawn requirements keep
their identifier with status `withdrawn`.

#### Scenario: New requirement is proposed

- **WHEN** a requirement is added to an OpenSpec change proposal
- **THEN** it receives the next free number in its AREA and a `proposed` row in the registry before the proposal is considered reviewable

### Requirement: FRG-PROC-003 — Spec before code

Production code SHALL only be written against requirements that exist in an OpenSpec
change proposal or an archived spec. Changes in behavior SHALL be proposed as OpenSpec
changes (proposal → specs delta → tasks) before implementation begins.

#### Scenario: Behavior change requested

- **WHEN** a new capability or behavior change is requested
- **THEN** an OpenSpec change is authored and its requirements registered before implementation commits are made

### Requirement: FRG-PROC-004 — Requirements verified by tagged tests

Every functional and non-functional requirement SHALL be verified by at least one
automated test that is tagged with the requirement identifier (e.g. a pytest marker or
test docstring reference), so that test results can be mapped back to requirements.

#### Scenario: Requirement implemented

- **WHEN** a requirement's implementation is completed
- **THEN** the test suite contains at least one test tagged with that requirement's ID, and it passes

### Requirement: FRG-PROC-005 — Traceability matrix

The project SHALL maintain a traceability matrix in `docs/traceability/` mapping each
requirement to its spec location, verifying tests, and implementing commits. The matrix
SHALL be regenerable from the repository (registry, test tags, git trailers) rather than
hand-maintained prose.

#### Scenario: Traceability audit

- **WHEN** the traceability matrix is regenerated
- **THEN** every `active` requirement resolves to at least one spec section, one tagged test, and one commit, and gaps are reported explicitly

### Requirement: FRG-PROC-006 — Threat analysis and risk register

The project SHALL maintain a STRIDE-based threat analysis and a living risk register in
`docs/security/`. Each identified risk SHALL be either accepted (with rationale) or
mitigated by one or more registered `FRG-SEC-*` / `FRG-NFR-*` requirements, which are
themselves test-verified per FRG-PROC-004.

#### Scenario: New attack surface added

- **WHEN** a change introduces new attack surface (network listener, parser of untrusted input, credential storage, outbound integration)
- **THEN** the threat analysis and risk register are updated as part of that change, before it is archived

### Requirement: FRG-PROC-007 — Branch-based integration, green main

No commits SHALL be made directly on `main`; all work SHALL happen on branches
(`change/<openspec-change-id>` for spec'd work, `research/<topic>` for research
artifacts, `process/<name>` for governance) and land on `main` only via `--no-ff`
merges, so per-commit `Refs:` trailers survive in history. A merge to `main` SHALL
only occur while the full test suite passes; merged branches SHALL be deleted.
Direct-commit prevention SHALL be automated via a `pre-commit` hook. The Phase 0
bootstrap root commit predates this requirement and is grandfathered. CI
re-enforcement of the green rule is deferred until a CI pipeline exists.

#### Scenario: Direct commit on main rejected

- **WHEN** a commit is attempted while `main` is checked out and no merge is in progress
- **THEN** the pre-commit hook rejects it and directs the author to a branch

#### Scenario: Branch merge accepted

- **WHEN** a branch is merged into `main` with `--no-ff` while the test suite is green
- **THEN** the merge commit is accepted and the branch is deleted after the merge

### Requirement: FRG-PROC-008 — Worktree isolation for concurrent agents

Any agent that mutates repository files SHALL work in its own git worktree on its own
branch, with one writer per file area; the orchestrator SHALL own all merges, conflict
resolution, and worktree cleanup after the branch merges. Research and analysis agents
SHALL be read-only, returning findings as text for the orchestrator to write.

#### Scenario: Concurrent implementation agents

- **WHEN** two or more file-mutating agents run concurrently
- **THEN** each operates in a distinct worktree and branch, and their work reaches the shared branch only through orchestrator-managed merges

#### Scenario: Research agent output

- **WHEN** a research agent completes its analysis
- **THEN** it has modified no repository files; its findings arrive as returned text that the orchestrator reviews and writes

### Requirement: FRG-PROC-009 — Spec approval gate

No implementation task of an OpenSpec change SHALL begin until the project owner
(Adrian) has explicitly approved the proposal. Approval SHALL be recorded in the
proposal file as an `## Approval` section naming the approver, date, and decision.
Phase transitions SHALL additionally pass through plan-mode gates presenting the
phase plan for approval before phase work (including sub-agent fan-outs) starts.

#### Scenario: Implementation attempted without approval

- **WHEN** implementation work is proposed for a change whose proposal lacks a recorded approval
- **THEN** the work does not proceed; the proposal is presented to the owner for decision first

#### Scenario: Approved change proceeds

- **WHEN** a proposal carries a recorded approval
- **THEN** implementation may begin, scoped to the approved requirements

### Requirement: FRG-PROC-010 — End-to-end slice verification harness

The project SHALL maintain a browser-driven end-to-end suite (Playwright) that
exercises the deployed application against its real container image — external
services mocked by default, optionally live via env-gated credentials — covering at
minimum: adding a series, interactive search with visible rejection reasons, grab →
download → automatic import → correctly renamed library file, library browsing in
the UI, and OPDS feed navigation with a file download served under the correct
comic MIME type. The suite SHALL run headless from a single command, capture
screenshots and traces on failure, and SHALL be green before a milestone is
presented for owner review.

#### Scenario: Hermetic slice run passes from one command

- **WHEN** the e2e entrypoint runs against a freshly built image with fixture
  ComicVine/indexer/DDL services and an empty /config volume
- **THEN** the suite drives first-run health, series add, interactive search
  (rejection reasons rendered verbatim), grab, import, UI browse, and OPDS download
  (byte-identical file, `application/vnd.comicbook+zip`) to a green verdict with no
  manual steps

#### Scenario: Failure produces actionable artifacts

- **WHEN** any e2e step fails
- **THEN** the runner saves a screenshot and Playwright trace for the failing step
  and the run exits non-zero naming the failed scenario

#### Scenario: Live tier is gated and optional

- **WHEN** news-server/API credentials are absent from the environment
- **THEN** the live-SABnzbd tier is skipped (reported as skipped, not failed) and
  the hermetic verdict is unaffected; with credentials present, the tier completes
  one real small download through to import

#### Scenario: Milestone review gate

- **WHEN** a milestone is presented for owner review
- **THEN** the most recent e2e run against that milestone's image is green and its
  run log is referenced in the review material

#### Scenario: Acceptance report is generated, not authored

- **WHEN** the e2e suite completes a milestone-acceptance run
- **THEN** an acceptance report is generated mechanically from the FRG-tagged
  scenario results (scenario → tagged requirement ids → pass/fail/skipped) with no
  hand-authored criteria matrix, and the owner's sign-off is recorded against that
  generated report in the change proposal's `## Acceptance` section

### Requirement: FRG-PROC-011 — Manual and README kept in sync with the application

The project SHALL maintain a user and administrator manual in `docs/manual/`, covering
user-facing behavior (what the application does and how to operate it) and
administration (deployment, configuration, environment variables, network exposure),
together with the repository `README.md` as top-level labelling/technical
documentation stating what the project is, its security and regulatory posture, the
development process (way of working), installation instructions, and (while the
repository is public) the roadmap and license/contribution posture per FRG-PROC-014.
The `README.md` is a controlled document on the same footing as the manual: a change
that alters any fact the README states — features, posture, process, installation,
roadmap milestones or their labels — SHALL update the README within the same change
(owner instruction 2026-07-10). Every OpenSpec change proposal SHALL declare its
manual impact — the manual/README sections it adds or updates, or an explicit "no
manual impact" statement with rationale. A change that alters manual-documented
behavior SHALL update the affected sections within the same change, before it merges
to `main`, and the merge gate SHALL verify that the declared manual impact was
carried out.

#### Scenario: Change alters documented behavior

- **WHEN** a change alters or adds user-facing or administrative behavior
- **THEN** the same change updates the affected `docs/manual/` sections before the change merges to `main`

#### Scenario: Change alters a fact the README states

- **WHEN** a change alters anything the README asserts — including roadmap
  milestone assignments, posture statements, or process descriptions
- **THEN** the same change updates the affected README section before merging,
  and the doc-consistency tests hold README claims to repository state (e.g.
  roadmap items citing requirement IDs carry the registry's milestone)

#### Scenario: Manual impact declared at proposal time

- **WHEN** an OpenSpec change proposal is authored
- **THEN** it contains a manual-impact declaration (sections touched, or "none" with rationale), reviewable at the FRG-PROC-009 approval gate

#### Scenario: Gate verifies sync

- **WHEN** a change reaches its merge gate
- **THEN** the gate confirms the manual matches the change's declared manual impact, and a mismatch blocks the merge until resolved

### Requirement: FRG-PROC-012 — SOUP register

The project SHALL maintain a SOUP (Software of Unknown Provenance) register in
`docs/security/soup-register.md` listing every direct third-party **runtime**
dependency of the backend and frontend with: name, version constraint, source,
intended purpose, the requirements or subsystems it supports, and license.
Development/test-only tooling SHALL be listed in a separate tools section (name,
version constraint, purpose). Any change that adds, removes, or upgrades a
dependency SHALL update the register within the same change. Register-vs-manifest
consistency SHALL be verified mechanically by `tools/soup_check.py`, which SHALL
exit non-zero on drift and SHALL pass at every merge gate.

Systematic known-anomaly/vulnerability review of register items is **deferred as a
documented future improvement**: it SHALL be performed with live advisory tooling
(e.g. `pip-audit`, `npm audit`, GitHub Dependabot) once the project has
network-connected CI, and the register's methodology note SHALL state this posture.
Until then the register SHALL NOT carry per-item anomaly-review verdicts —
knowledge-based (non-live) vulnerability assessments are prohibited as
audit-misleading; the anomaly column reads "Deferred — see methodology".

#### Scenario: Dependency added or upgraded

- **WHEN** a change adds, removes, or upgrades a direct dependency in `pyproject.toml` or `package.json`
- **THEN** the same change updates the corresponding SOUP register row (inventory fields only; no anomaly verdict is fabricated)

#### Scenario: Drift blocks the gate

- **WHEN** `tools/soup_check.py` finds a direct manifest dependency without a matching register row, a register row without a manifest entry, or a version-constraint mismatch
- **THEN** it exits non-zero and the merge gate blocks until the register is reconciled

#### Scenario: Lockfile remains the authoritative pin

- **WHEN** transitive dependencies change solely via lockfile resolution, with no direct-dependency change
- **THEN** no register update is required; the lockfile remains the authoritative pin of the full tree

#### Scenario: Anomaly review activates with network CI

- **WHEN** network-connected CI capable of live advisory queries becomes available
- **THEN** systematic anomaly review is introduced (tooling, cadence, and recording format), and the methodology note is updated from the deferred posture in the same change

### Requirement: FRG-PROC-013 — Release tagging

Every change merged to `main` from change 7 (`m1-ui-opds-deploy`) onward SHALL be
marked by an annotated git tag on its merge commit, following SemVer: completing a
milestone sets the MINOR line (M1 = 0.1.x, M2 = 0.2.x, M3 = 0.3.x) and each
subsequent merged change within a milestone increments PATCH. The first tag SHALL be
`v0.1.0` at change 7's merge (M1 feature-complete) and `v0.1.1` at change 8's merge
(M1 acceptance-certified). The tag message SHALL name the change id and the FRG
requirement refs the change implements. Tags — together with the `main` branch they
point into — SHALL be pushed to `origin` when created, so every tag is a restore
point that survives loss of the working environment. Tags SHALL never be moved or
deleted once pushed; a bad release is corrected by a new PATCH tag.

Every such release SHALL additionally be recorded as **first-class, auditable release
notes**, so the release history is self-documenting rather than reconstructable only
from tag messages:

- a `CHANGELOG.md` entry at the repository root for the release version, in a
  Keep-a-Changelog-style format, listing the user- and administrator-facing changes
  grouped as Added / Changed / Fixed / Security, the FRG requirement ids the release
  delivers, and any upgrade or migration notes;
- the backend `pyproject.toml` `version` set to the release version, so the running
  application reports its true version rather than a stale placeholder;
- a published GitHub Release (`gh release create`) for the tag, carrying that
  CHANGELOG entry as its body.

The `CHANGELOG.md` entry and the `pyproject.toml` version bump SHALL land in the
**same merged change** as the code they describe, before it merges to `main`; the
annotated tag and the GitHub Release SHALL be created immediately after the merge
commit exists, in the same merge gate, from that same CHANGELOG entry. A release is
not complete until its CHANGELOG entry, tag, pushed `main`, and GitHub Release all
exist. This requirement applies **retroactively** to every tag created before it was
adopted: `CHANGELOG.md` and a GitHub Release SHALL exist for each existing tag
(v0.1.0 through v0.2.8), reconstructed from their tag messages and archived change
proposals.

#### Scenario: Change merge creates a tag

- **WHEN** a change merges to `main` at or after change 7
- **THEN** the merge gate creates an annotated SemVer tag on the merge commit whose message names the change id and its FRG refs

#### Scenario: Tags are pushed restore points

- **WHEN** a tag is created
- **THEN** the tag and `main` are pushed to `origin` in the same gate, and checking out the tag reproduces the released tree

#### Scenario: Tags are immutable

- **WHEN** a defect is found in a tagged release
- **THEN** the fix lands as a new merged change with a new PATCH tag; the existing tag is never moved or deleted

#### Scenario: Release carries a CHANGELOG entry and a matching version

- **WHEN** a change that will be tagged as a release merges to `main`
- **THEN** the same change has added its version's `CHANGELOG.md` entry (Added/Changed/Fixed/Security + FRG refs + upgrade notes) and set `backend/pyproject.toml` `version` to the release version, before the merge

#### Scenario: Release is published as a GitHub Release

- **WHEN** a release tag is created and pushed
- **THEN** a GitHub Release is published for that tag in the same gate, carrying the CHANGELOG entry as its body

#### Scenario: The release record is complete for existing tags

- **WHEN** the release-notes requirement is adopted
- **THEN** `CHANGELOG.md` and a published GitHub Release exist for every prior tag (v0.1.0..v0.2.8), reconstructed from tag messages and archived proposals

### Requirement: FRG-PROC-014 — Public repository labelling and posture

`README.md`, as the repository's public-facing labelling, SHALL — while the
repository is public — state: (a) the project's purpose, framed around managing a comic
library the user owns (DRM-free purchases, public-domain scans), metadata, and
OPDS reading — with acquisition described content-neutrally and no indexer/DDL
source promoted in the lead; (b) the license, matching the
`LICENSE` file; and (c) the contribution posture (source-available personal tool
and process demonstration; input not solicited). Feature claims in the README SHALL
describe only shipped behavior; unshipped intentions live in `docs/roadmap.md`
per FRG-PROC-018, and the README SHALL retain an explicit Roadmap heading that
links to `docs/roadmap.md` without restating its entries. Each major feature
section SHALL carry a screenshot whose caption
links to the governing `FRG-*` requirement ID(s) and the relevant spec and/or
manual document, and every such link SHALL resolve: referenced IDs exist in
`docs/traceability/requirements-registry.md`, and referenced paths exist in the
repository. No controlled document (`README.md`, `CLAUDE.md`, `docs/manual/`)
retains the claim that foragerr is private or not released publicly.

- **Notes**: The "future work" example in the labelling scenario below was
  amended from "the Humble Bundle importer and public-domain archive import" to
  the public-domain archive import alone because the Humble Bundle importer
  shipped in `m6-humble-source` — it is now a documented feature with its own
  README tour section, not forward-looking work.

#### Scenario: README labelling is complete and consistent

- **WHEN** the documentation-consistency checks run against `README.md`
- **THEN** the README names the GPL-3.0 license and links `LICENSE`, states the
  source-available contribution posture, contains no "not released publicly" /
  "private tool" self-description, and contains a Roadmap heading that links to
  `docs/roadmap.md`, and `docs/roadmap.md` lists the public-domain archive
  import as future work

#### Scenario: Screenshot walkthrough is traceable

- **WHEN** the README's embedded screenshot sections are checked
- **THEN** every screenshot image path resolves to a file tracked in the
  repository, and every `FRG-*` ID cited in a screenshot caption exists in
  `docs/traceability/requirements-registry.md`, and every spec/manual path cited
  in a caption exists

#### Scenario: Roadmap never advertises unshipped work as shipped

- **WHEN** a README feature section (outside the Roadmap heading) describes a
  capability
- **THEN** that capability corresponds to requirements with implemented status in
  the requirements registry

### Requirement: FRG-PROC-015 — Repository history hygiene

The repository SHALL only be made — and remain — public while a full-git-history
secret scan (gitleaks, covering all refs) reports no verified findings. The scan
result (tool, version, commit range, finding count, disposition of any findings)
SHALL be recorded as evidence in the change that flips visibility, and the scan
SHALL be re-run and re-recorded before any subsequent history-affecting operation
(force-push, history rewrite) is pushed to the public remote.

#### Scenario: Pre-flip scan gate

- **WHEN** the visibility flip is prepared
- **THEN** a gitleaks scan across the full history of all refs has been run and
  recorded with zero unresolved findings, and the recorded evidence names the
  scanned HEAD commit

#### Scenario: Finding blocks the flip

- **WHEN** the full-history scan reports a verified secret
- **THEN** the repository is not made public (or a public repo is not pushed to)
  until the secret is revoked and the finding's disposition is recorded

### Requirement: FRG-PROC-016 — Known-anomalies register

`docs/security/known-anomalies.md` SHALL record every anomaly the owner
decides to accept rather than fix — a shipped defect, a process deviation, or
an exposure persisting in published artifacts — as an entry with a stable,
never-reused `KA-<NNN>` identifier carrying: a description, the
location/scope, an impact evaluation, the owner's decision with date and
rationale, compensating mitigations, and an explicit review trigger. Entries
SHALL never be deleted: an anomaly later fixed is marked resolved with a
reference to the fixing change. A change whose release accepts a new anomaly
SHALL reference the KA identifier in its release notes. The register is a
controlled document: its structural consistency SHALL be verified by tagged
tests.

#### Scenario: Accepting an anomaly creates a register entry

- **WHEN** the owner decides to accept a defect, deviation, or exposure
  rather than fix it
- **THEN** the register gains a `KA-<NNN>` entry with description,
  location/scope, impact evaluation, owner decision (date + rationale),
  mitigations, and review trigger, in the same change that records the
  decision

#### Scenario: Register consistency is test-enforced

- **WHEN** the documentation-consistency tests run
- **THEN** every register entry has a unique `KA-<NNN>` identifier and all
  required fields, and identifiers are never renumbered or reused

#### Scenario: A fixed anomaly is resolved, not erased

- **WHEN** a previously accepted anomaly is later eliminated by a change
- **THEN** its entry is marked resolved with a reference to that change, and
  the entry (and its identifier) remains in the register permanently

### Requirement: FRG-PROC-017 — Regenerable README screenshots

The README tour's screenshots SHALL be regenerable by one command
(`tools/refresh-readme-shots.sh`): it starts the application against the
public-domain demo library, populates it when empty, captures the tour's
screen set via the committed capture script, optimizes every image to the
in-repo asset budget (≤ ~300 KB), and exits non-zero if any expected shot is
missing or over budget. A change that alters the shipped UI's appearance
SHALL re-run the tool and commit the refreshed assets before merging, so the
public labelling never lags the shipped design.

#### Scenario: One command produces the full tour set

- **WHEN** `tools/refresh-readme-shots.sh` runs on a machine with the demo
  library available
- **THEN** every screenshot the README embeds is regenerated at the expected
  path within budget, and the tool exits zero only when the set is complete

#### Scenario: UI-affecting changes refresh the tour

- **WHEN** a change alters the shipped UI's appearance
- **THEN** the same change commits refreshed README assets produced by the
  tool, verified at the merge gate

#### Scenario: Structural pin without the demo environment

- **WHEN** the documentation-consistency tests run in a hermetic environment
- **THEN** they verify the tool exists and is executable and that the README's
  embedded assets exactly match the capture script's shot set, without
  requiring the demo library or a browser

### Requirement: FRG-PROC-018 — Roadmap single source of truth

The project SHALL maintain `docs/roadmap.md` as the only controlled document
containing forward-looking content — unshipped milestones, planned features,
and future intentions. Each roadmap entry SHALL name its milestone and, where
requirement ids are already allocated, cite them. All other controlled
documents (`README.md`, `docs/manual/**`) SHALL link to `docs/roadmap.md`
rather than restate its content; incidental forward references they cannot
avoid SHALL appear on an explicit allowlist that names the file and the
permitted token, so every exception is reviewable. The merge gate SHALL enforce
this mechanically with two committed-text checks:

- **Containment**: future-milestone tokens and planned-phrasing markers do not
  appear in controlled documents outside `docs/roadmap.md`, except where
  allowlisted.
- **Freshness**: no `FRG-*` id that `docs/roadmap.md` presents as planned has
  `implemented` status in `docs/traceability/requirements-registry.md`.

This rule is deliberately narrow (the roadmap instance only); generalizing
documentation-consistency checking to other cross-document facts requires its
own proposal.

#### Scenario: Shipping a roadmap item forces the roadmap update

- **WHEN** a requirement id listed as planned in `docs/roadmap.md` reaches
  `implemented` status in `docs/traceability/requirements-registry.md`
- **THEN** the freshness check fails until the same change removes or reworks
  that roadmap entry

#### Scenario: Forward-looking text outside the roadmap is rejected

- **WHEN** a controlled document other than `docs/roadmap.md` contains a
  future-milestone token or planned-phrasing marker that is not allowlisted
- **THEN** the containment check fails, naming the file and the offending token

#### Scenario: Allowlist entries are explicit

- **WHEN** an incidental forward reference must remain in a controlled document
- **THEN** the containment check passes only via an allowlist entry that pairs
  that specific file with that specific token

### Requirement: FRG-PROC-019 — Accessibility scan in the e2e gate

The e2e harness SHALL include an accessibility tier: an axe-core WCAG 2.1 A/AA scan of the authenticated core screens that fails the suite on any serious- or critical-impact violation, so accessibility conformance (FRG-UI-038) is enforced wherever the e2e gate runs rather than depending on one-off audits.

- **Milestone**: M9 (m9-a11y-fixes)
- **Source**: Owner direction 2026-07-16 ("the tooling might be worth pulling in to the release cycle").
- **Notes**: Zero-tolerance with no baseline file — the fixes land in the same change, so the clean state is the starting invariant. axe-core is e2e dev tooling (SOUP-register-exempt per the harness's existing note, like Playwright).

#### Scenario: A regression fails the harness

- **WHEN** a change reintroduces a serious-impact WCAG violation on a scanned screen and the e2e suite runs
- **THEN** the a11y spec fails naming the rule and the offending nodes, and the run exits non-zero
