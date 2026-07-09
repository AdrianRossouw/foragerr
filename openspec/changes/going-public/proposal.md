# going-public — open the foragerr repository to the public

## Why

foragerr has been developed from day one as a working demonstration of regulated
software development practice (the formicary.ai context), but that demonstration is
currently invisible: the repository is private. Opening it makes the practice
inspectable — the aim is not users or contributors, only to stop doing the work
privately. Going public forces three things the private posture let us defer: a
README that introduces the project to a general reader on its own terms (managing a
comic library the user owns), a license, and confidence that nothing in the
repository or its history is unsafe to expose.

## What Changes

- **README repositioning.** The "not released publicly" paragraph is removed. The
  lead becomes the library-management story: import/renaming of comics the user
  owns (DRM-free purchases such as Humble Bundle, public-domain scans from e.g.
  Digital Comic Museum), ComicVine metadata, and OPDS reading on the user's own
  devices. Acquisition is described content-neutrally in the Sonarr/Radarr idiom
  ("integrates with your existing usenet setup") rather than front-loading specific
  indexers. An explicit Roadmap section lists the Humble Bundle importer and
  loose/public-domain archive import as *future* changes — the README never
  advertises unshipped features as shipped.
- **README screenshot walkthrough.** Each major README section embeds a UI
  screenshot whose caption links to the governing `FRG-*` requirement IDs, the spec
  section, and the manual page — making the regulated-development claim demonstrable
  (screenshot → requirement → tagged test). Screenshots are captured from a demo
  library populated with public-domain comics only; images live in-repo.
- **License.** `LICENSE` (GPL-3.0) added at the repo root, referenced from README
  and `pyproject.toml`, matching the Sonarr/Radarr/Mylar3 heritage foragerr studies.
- **Contribution posture.** README states plainly: source-available personal tool
  and process demonstration; issues remain enabled but input is not solicited and
  may go unanswered.
- **"Private tool" language sweep.** `CLAUDE.md` and `docs/manual/index.md` drop the
  private/never-released framing. Risk-register rationales that lean on "private
  tool" (at minimum RISK-015 default-enabled DDL provider, RISK-020 no-auth
  Tailscale-only exposure) are re-reviewed and reworded to rest on the *deployment*
  posture (single-user, self-hosted, tailnet-scoped) — which is unchanged — rather
  than on repository secrecy.
- **History hygiene gate.** A full-git-history secret scan (gitleaks) must pass
  before the visibility flip, with the result recorded as evidence in the change.
- **Visibility flip.** The actual GitHub private→public switch is the owner's manual
  admin action, documented as the final task; nothing in this change performs it.

## Non-goals

- **No production code.** This is a docs/process/labelling change; backend and
  frontend behavior are untouched (screenshot capture drives the existing app,
  it does not modify it).
- **No new features.** The Humble Bundle importer and loose/public-domain archive
  import are roadmap entries only; each will be its own future OpenSpec change with
  its own requirements and threat-model updates.
- **No deployment-posture change.** No-auth Tailscale-only exposure (RISK-020) and
  the default-enabled DDL provider (RISK-015) keep their accepted-risk status; this
  change only re-words their rationales for a public audience. If re-review
  concludes a posture change *is* warranted, that becomes its own proposal.
- **No community infrastructure.** No CONTRIBUTING.md workflow, issue templates,
  CI badges, code of conduct, or published container image.
- **No relicensing of history.** GPL-3.0 applies from this change forward; no
  attempt to retroactively stamp prior releases.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `dev-process`: two new requirements —
  - **FRG-PROC-014 — Public repository labelling and posture**: README is the
    public-facing labelling; it must state purpose (framed around managing the
    user's own library), license, and contribution posture, and its feature claims
    must describe only
    shipped behavior, with the screenshot walkthrough linking sections to governing
    requirement IDs, specs, and manual pages.
  - **FRG-PROC-015 — Repository history hygiene**: the repository may only be (and
    remain) public while a full-history secret scan passes; scan evidence is
    recorded, and the gate re-runs when history-affecting operations occur.
- `dep`: one new requirement —
  - **FRG-DEP-014 — Open-source license (GPL-3.0)**: the repository carries a
    GPL-3.0 `LICENSE` at the root, declared in `pyproject.toml` and README labelling.

## Impact

- **Files**: `README.md` (rewrite + screenshots), `LICENSE` (new),
  `docs/readme-assets/` or similar for screenshot images (new), `CLAUDE.md`,
  `docs/manual/index.md`, `docs/security/risk-register.md` (rationale rewording,
  RISK-015/RISK-020), `pyproject.toml` (license metadata),
  `openspec/specs/dev-process/spec.md` + `openspec/specs/dep/spec.md` (delta specs),
  `docs/traceability/requirements-registry.md` (allocate FRG-PROC-014, FRG-PROC-015,
  FRG-DEP-014).
- **Manual impact (FRG-PROC-011)**: `docs/manual/index.md` intro wording only; no
  behavioral sections change (no application behavior changes).
- **SOUP (FRG-PROC-012)**: none — gitleaks is a development-time gate tool run
  outside the shipped artifact, not a runtime dependency; no register entry.
- **Security (FRG-PROC-006)**: no new attack surface (no listener/parser/credential/
  integration changes). Risk-register rationale updates for RISK-015/RISK-020 happen
  in this change; the history secret scan is recorded as gate evidence.
- **External actions (owner)**: GitHub visibility flip; optionally repo description/
  topics to match the new positioning.

## Approval

Approved by Adrian, 2026-07-09 ("go ahead and make the changes"), with the
following owner-retained actions: pushing to GitHub and all repository settings
(including the visibility flip) are handled by Adrian personally.
