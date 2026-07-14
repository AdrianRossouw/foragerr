# site-regulated-story

## Why

foragerr's most distinctive property is not the comic manager — it is the regulated,
requirement-traced process it is built under, and today that story is only visible to
someone willing to read a repository. A public site gives the process a front door:
the method, the release history, and the evidence artifacts, presented so a visitor
can follow one requirement from intent to proof. A Claude Design exploration
("Foragerr Site", project `7c792029-57c1-46cc-b7f1-7be8ba30cb1b`) established the
visual direction; this change turns it into a real, honest site.

The governing principle, set by the owner: **every fact on the site is generated
from repository artifacts, or it does not appear.** The design's placeholder content
(a penetration test, SBOMs, acceptance reports, CI enforcement, an MIT license, an
invented 8-release history) is layout only — none of it ships. On a site whose
subject is trustworthiness, a single checkable false claim defeats the purpose.

## What Changes

- New `site/` static-site generator (Python, stdlib-only) that renders five pages —
  Overview, The Method, Timeline, Trust Center, Product — from committed repo
  artifacts: `docs/traceability/requirements-registry.md`,
  `docs/traceability/matrix.md`, `CHANGELOG.md`, `docs/security/risk-register.md`,
  and git tags. The generator fails the build if a source artifact is missing or
  unparseable; no displayed number, status, path, or history entry is hand-maintained.
- Visual language transcribed from the Claude Design exploration (the app's own
  design tokens, Hero direction "A · Claim" with the follow-one-requirement trace
  card; the hero-direction switcher is not built). The Method page keeps the
  "How to weigh this" honesty callout.
- Vanity metrics replaced by evidence metrics: the stat strip shows registry-derived
  counts (requirements, tagged releases) and **traced-test coverage** (requirements
  with passing tagged tests, from the matrix) instead of a raw test count.
- The repo's **first GitHub Actions workflow**: on push to `main`, build the site and
  deploy to GitHub Pages (`adrianrossouw.github.io/foragerr`), keeping the site in
  sync with source automatically. Actions pinned by commit SHA, least-privilege
  token permissions (`pages: write`, `id-token: write`).
- New `SITE` AREA (FRG-SITE-001..006) in the commit standard and requirements
  registry.
- README gains a link to the site.

## Capabilities

### New Capabilities
- `site`: the public regulated-software-story site — generated-facts-only rule,
  information architecture and honesty content, timeline and trust-center
  generation, deployment pipeline, and positioning/licensing accuracy.

### Modified Capabilities

None. The site consumes existing artifacts read-only; no behavior of the
application, process, or release flow changes at the requirement level.

## Impact

- **Code**: new `site/` directory (generator script, templates, static CSS ported
  from the design-system tokens); new `.github/workflows/pages.yml`; README edit.
  No backend/frontend product code touched.
- **Dependencies / SOUP**: generator is stdlib-only (no new Python deps). The
  workflow introduces GitHub-hosted actions (`actions/checkout`,
  `actions/configure-pages`, `actions/upload-pages-artifact`,
  `actions/deploy-pages`) — recorded in `docs/security/soup-register.md` in this
  change, pinned by SHA.
- **Security**: new outward-facing surface (public static site) and a new
  supply-chain surface (first CI workflow). `docs/security/` updated in this change:
  risk-register entry for workflow/supply-chain risk (pinned actions, least-privilege
  `GITHUB_TOKEN`, no secrets in the build) and a threat-model note that the site is
  static output with no listener, no user input, and no credentials.
- **Manual impact**: `README.md` labelling (site link). `docs/manual/` — none:
  the site does not change application behavior; site content itself is governed
  by FRG-SITE requirements, not the manual.
- **Process**: `/release` is unaffected (deploy rides push-to-main); the release
  skill gains no mandatory step. Owner flips the repo's Pages setting to
  "GitHub Actions" once (settings are not in the repo).

## Non-goals

- No product marketing page beyond the single Product page; no pricing/analytics/
  tracking of any kind.
- No fabricated or forward-dated evidence: no pentest, SBOM, acceptance-report, or
  CI-enforcement claims until those artifacts actually exist in the repo.
- No custom domain in this change (can layer onto Pages later without code change).
- No `foragerr.github.io` org (name taken); the project-pages URL is the target.
- No CI test-gate in this change — the workflow builds and deploys the site only.
  A tests + `trace.py` + `soup_check.py` CI gate is a candidate follow-up; until
  then site wording stays "enforced at merge gates", which is what is true.
- No JavaScript framework or build toolchain for the site; static HTML/CSS output,
  progressive enhancement only if ever needed.
