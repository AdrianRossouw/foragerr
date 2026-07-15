# site — public regulated-software-story site

## ADDED Requirements

### Requirement: FRG-SITE-001 — Generated facts only
The site generator SHALL derive every displayed fact — counts, statuses, versions,
dates, requirement IDs, file paths, commit hashes, and history entries — from
committed repository artifacts (`docs/traceability/requirements-registry.md`,
`docs/traceability/matrix.md`, `CHANGELOG.md`, `docs/security/risk-register.md`,
`LICENSE`, git tags) at build time. Page templates MUST NOT contain hand-maintained
factual values, and the build MUST fail (non-zero exit) when a source artifact is
missing or unparseable rather than render a page with absent or stale facts.

#### Scenario: Facts track the source artifacts
- **WHEN** the generator is run against a fixture repository whose registry contains
  a known number of requirements and whose CHANGELOG contains a known set of releases
- **THEN** the built pages display exactly those counts and releases, with no other
  factual values present

#### Scenario: Missing source artifact fails the build
- **WHEN** the generator is run with one required source artifact absent or
  structurally unparseable
- **THEN** the generator exits non-zero, names the offending artifact, and writes no
  partial site output

### Requirement: FRG-SITE-002 — Information architecture and honest framing
The site SHALL consist of five pages — Overview, The Method, Timeline, Trust Center,
and Product — with shared navigation, following the approved Claude Design direction
(hero "A · Claim" with a follow-one-requirement trace card). The Overview hero's
trace card MUST be populated from a real requirement row of the traceability matrix
(spec path, tagged tests, commits). The Method page MUST include the "How to weigh
this" callout stating that the code is AI-authored, that no human has read every
line, and that the records are an account of how it was made, not a claim of
flawlessness.

#### Scenario: Five pages with shared navigation
- **WHEN** the site is built
- **THEN** output contains the five pages, each carrying navigation links to the
  other four

#### Scenario: Trace card is real
- **WHEN** the Overview page is built
- **THEN** the hero trace card's requirement ID exists in the requirements registry,
  and its spec path, test reference, and commit hash are taken from that
  requirement's traceability-matrix row

#### Scenario: Honesty callout present
- **WHEN** the Method page is built
- **THEN** it contains the "How to weigh this" callout including the statement that
  no human has read every line and that discipline, not perfection, is the claim

### Requirement: FRG-SITE-003 — Timeline generated from release history
The Timeline page SHALL be generated from `CHANGELOG.md` release entries
cross-checked against git tags: every rendered release MUST correspond to an
existing annotated tag, and MUST display the version, date, and summary content
from its CHANGELOG entry, including the requirement IDs it references. The
generator MUST NOT invent, omit, or reorder releases relative to the CHANGELOG.

#### Scenario: Releases mirror the CHANGELOG
- **WHEN** the Timeline page is built
- **THEN** it contains one entry per CHANGELOG release, newest first, each showing
  the CHANGELOG's version, date, and summary, and each version matches an existing
  git tag

#### Scenario: Untagged CHANGELOG entry fails the build
- **WHEN** the CHANGELOG contains a release entry whose version has no corresponding
  git tag
- **THEN** the build fails, naming the inconsistent version

### Requirement: FRG-SITE-004 — Trust center renders existing evidence only
The Trust Center SHALL index only evidence artifacts that exist in the repository at
build time — evidence documents (requirements registry, traceability matrix, risk
register, threat model, SOUP register, known-anomalies register, release records) and
process/governance artifacts (dev-process spec, commit standard, archived change
proposals with their recorded approvals, manual, history scan) — each linking to its
file in the repository, with any displayed counts (such as archived changes and
recorded approvals) derived at build time. The risk table MUST be rendered from
`docs/security/risk-register.md`. Aggregate metrics MUST be evidence metrics derived
from the registry and matrix — including traced-test coverage stated against the
requirements it can apply to (implemented requirements with tagged tests over total
implemented) and a coverage breakdown by requirement status — and the site MUST NOT
display standalone volume metrics (such as a raw test count) or a coverage ratio
whose denominator mixes statuses that cannot carry tests (unbuilt backlog) with
those that must. The site MUST NOT make positive claims about artifacts that do not
exist (penetration tests, SBOMs, acceptance reports, CI enforcement); it MAY state
their absence explicitly within a single dedicated absence section, each absence
citing the committed document that records the deferral or decision.

#### Scenario: Every indexed artifact exists
- **WHEN** the Trust Center page is built
- **THEN** every artifact card's repository path exists in the working tree, and its
  link resolves to that path in the repository hosting UI

#### Scenario: Nonexistent evidence is not claimed
- **WHEN** the built site's pages are scanned, excluding the dedicated absence
  section
- **THEN** they contain no references to penetration tests, SBOMs, acceptance
  reports, or CI-enforced controls while no such artifacts exist in the repository

#### Scenario: Absences are stated only in the absence section
- **WHEN** the Trust Center's absence section is rendered
- **THEN** each entry states that the control is not in place and cites the
  committed document recording its deferral, and the same phrases appearing
  outside the absence section still fail the build

#### Scenario: Coverage breakdown is derived by status
- **WHEN** the Trust Center's coverage panel is built
- **THEN** it shows, computed from the traceability matrix: implemented
  requirements with tagged tests over total implemented, the count of approved
  not-yet-built requirements, and the count of process rules split by
  machine-tested versus hook/gate-enforced

#### Scenario: Coverage metric replaces test count
- **WHEN** the stat strip is built
- **THEN** it shows implemented-requirement test coverage computed from the
  traceability matrix, and shows neither a standalone total-test-count figure nor
  a coverage ratio over all non-withdrawn requirements

### Requirement: FRG-SITE-005 — Automated Pages deployment from main
The repository SHALL contain a GitHub Actions workflow that, on every push to
`main`, builds the site with the generator and deploys the output to GitHub Pages.
The workflow MUST pin all third-party actions to full commit SHAs and MUST grant the
job only the permissions Pages deployment requires (`contents: read`,
`pages: write`, `id-token: write`).

#### Scenario: Workflow is pinned and least-privilege
- **WHEN** the workflow file is inspected
- **THEN** every `uses:` reference is pinned to a full-length commit SHA and the
  declared permissions are exactly `contents: read`, `pages: write`,
  `id-token: write`

#### Scenario: Push to main deploys the site
- **WHEN** a commit is pushed to `main`
- **THEN** the workflow builds the site from that commit's artifacts and publishes
  it to GitHub Pages

### Requirement: FRG-SITE-006 — Positioning and licensing accuracy
Site copy SHALL follow the project's positioning rules: the library is described as
one the user owns, acquisition is described content-neutrally, and AI authorship is
disclosed without overselling. The footer's license statement MUST match the
repository `LICENSE` (GPL-3), and repository links MUST point to the actual
repository. The built site MUST contain none of a maintained banned-phrase list
(at minimum: piracy meta-language, "non-infringing", and license names other than
the actual license).

#### Scenario: License and links are accurate
- **WHEN** the site is built
- **THEN** the footer license text matches the LICENSE file's license family and
  all repository links point to the real repository URL

#### Scenario: Banned phrases absent
- **WHEN** the built site's pages are scanned against the banned-phrase list
- **THEN** no page contains any listed phrase
