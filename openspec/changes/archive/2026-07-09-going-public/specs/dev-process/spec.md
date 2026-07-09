# dev-process delta — going-public

## ADDED Requirements

### Requirement: FRG-PROC-014 — Public repository labelling and posture

`README.md`, as the repository's public-facing labelling, SHALL — while the
repository is public — state: (a) the project's purpose, framed around managing a comic
library the user owns (DRM-free purchases, public-domain scans), metadata, and
OPDS reading — with acquisition described content-neutrally and no indexer/DDL
source promoted in the lead; (b) the license, matching the
`LICENSE` file; and (c) the contribution posture (source-available personal tool
and process demonstration; input not solicited). Feature claims in the README SHALL
describe only shipped behavior; unshipped intentions appear only under an explicit
Roadmap heading. Each major feature section SHALL carry a screenshot whose caption
links to the governing `FRG-*` requirement ID(s) and the relevant spec and/or
manual document, and every such link SHALL resolve: referenced IDs exist in
`docs/traceability/requirements-registry.md`, and referenced paths exist in the
repository. No controlled document (`README.md`, `CLAUDE.md`, `docs/manual/`)
retains the claim that foragerr is private or not released publicly.

#### Scenario: README labelling is complete and consistent

- **WHEN** the documentation-consistency checks run against `README.md`
- **THEN** the README names the GPL-3.0 license and links `LICENSE`, states the
  source-available contribution posture, contains no "not released publicly" /
  "private tool" self-description, and contains a Roadmap heading under which the
  Humble Bundle importer and public-domain archive import are listed as future work

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
