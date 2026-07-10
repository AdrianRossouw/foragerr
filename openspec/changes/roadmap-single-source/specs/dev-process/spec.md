# dev-process — delta for roadmap-single-source

## ADDED Requirements

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

## MODIFIED Requirements

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

#### Scenario: README labelling is complete and consistent

- **WHEN** the documentation-consistency checks run against `README.md`
- **THEN** the README names the GPL-3.0 license and links `LICENSE`, states the
  source-available contribution posture, contains no "not released publicly" /
  "private tool" self-description, and contains a Roadmap heading that links to
  `docs/roadmap.md`, and `docs/roadmap.md` lists the Humble Bundle importer and
  public-domain archive import as future work

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
