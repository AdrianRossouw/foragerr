# dev-process Spec Delta

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
