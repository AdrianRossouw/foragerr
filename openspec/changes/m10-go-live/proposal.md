# m10-go-live — qualification, release pipeline, and hardening posture (milestone pre-design)

## Why

M10 is the go-live milestone of the 1.0 cut (owner decision 2026-07-11:
M6 sources → M8 auth → M9 UI refinement → M10 go-live). This change record was
**pre-designed 2026-07-15** while top-tier design capacity was available; it is
the design authority for the milestone and is NOT apply-ready by intent — at
M10 kickoff it splits into implementable changes (decomposition below), each
with its own delta specs, tasks, and approval. It does not jump the queue:
M9 (designer re-engagement) precedes M10.

The milestone's thesis: 1.0 is not a feature release but a **qualification
release** — pentest, IQ/OQ/PQ deployment qualification, and a formal release
pipeline are three legs of the same stool. Most of the work is
decide-and-document: converting positions the project already holds de facto
(TLS delegated to deployment, credentials-only at-rest encryption, Docker as
the only deployment) into committed, citable decisions before an external
reviewer states them for us.

Owner decisions from the pre-design review (2026-07-15) shaping everything:

- **Docker-only support.** The published image is the sole supported
  deployment; source runs are a development mode, unsupported and unqualified.
- **Credentials-only at-rest encryption** stays the design; full-disk
  encryption is recommended to operators; full-database encryption is
  rejected with recorded rationale.
- **Operator/vendor split for qualification.** The repo ships protocols and
  tooling; executed records from the owner's production server stay out of
  the repository permanently. The production environment is out of scope for
  the project, in every artifact, by design.
- **No CI commits.** The pipeline produces artifacts (image, qualification
  record); only the session-driven release flow commits, on branches, under
  the hooks. No bot pushes to main.
- **No personal third-party credentials in CI.** Reference-environment OQ
  verifies account-backed integrations (Humble, ComicVine, Newznab indexers)
  against fixtures; live checks happen at operator qualification.
- **Scoped credentials with feedback.** GHCR publishing uses the ephemeral
  workflow `GITHUB_TOKEN` only; the session PAT shrinks to a fine-grained,
  single-repo token, with a committed check that reports over-broad scope.

## What Changes

- **Release pipeline**: GHCR image publishing from the tag-triggered workflow
  (`GITHUB_TOKEN`, explicit least-privilege `permissions:` block, test-asserted
  like `pages.yml`); build-once → qualify → push → publish ordering; OCI
  revision/version labels; SBOM generated from the SOUP register; pinned
  actions; `/release` skill grows the qualify-and-record steps. Activates the
  queued release-process decision (dev/rc/release SemVer, release gate as
  coverage backstop) as the first M10 change.
- **Deployment security posture**: HTTP security headers middleware (CSP,
  X-Content-Type-Options, frame-ancestors, Referrer-Policy); opt-in
  trusted-proxy config fixing the Secure-cookie-behind-TLS-proxy gap and
  revising the X-Forwarded-For position; manual section for TLS (Tailscale /
  reverse proxy), FDE recommendation, container run flags
  (no-new-privileges, cap_drop, read-only rootfs); posture decisions
  document the pentest can cite.
- **V&V strategy + IQ/OQ/PQ**: a strategy document naming the existing
  requirement/test/traceability machinery as verification and structured
  dogfood as validation; IQ/OQ as executable checks against a running
  container emitting non-leaky records keyed to tag + commit + image digest;
  PQ protocol derived from the e2e user journeys; site renders qualification
  chips per release (new FRG-SITE id).
- **Audit durability**: the owner-approved post-M8 follow-up (durable audit
  store) lands in this milestone.
- **Pentest**: scope statement committed first (seeded throwaway instance,
  production out of scope), findings-and-remediations summary committed after.
- **Hardening sweep**: decide-and-document items — health endpoint disclosure,
  DoS envelope (request body caps, WS connection caps, zipfile-OOM position),
  downgrade warning, dependency-audit cadence, error/debug hygiene, and
  re-acceptance or closure of aged backlog residuals (FRG-DEP-012, RISK-008).

## Capabilities

Declared for orientation; delta specs are written by the implementing changes,
not this record: `dev-process` (release pipeline, FRG-PROC-013 amendment),
`dep` (image publishing, posture, trusted proxy), `site` (qualification-record
rendering, evidence cards, absence flips), `auth`/`sec` (headers, audit
durability), plus a probable new `VAL` area (qualification requirements — AREA
table in `docs/process/commit-standard.md` updated by the allocating change).
**No new requirement ids are allocated by this pre-design** (registry lesson:
ids belong to the implementing change's proposal).

## Decomposition at M10 kickoff (~gate-sized)

1. `m10-release-pipeline` — GHCR publish, workflow permissions, OCI labels,
   SBOM from SOUP register, pinned actions, token scoping + `token_check`,
   credential inventory (threat-model delta: CI/supply-chain surface),
   dev/rc/release SemVer, `/release` growth. First change, as previously
   decided ([[release-process-idea]]).
2. `m10-deployment-posture` — headers middleware, trusted-proxy + Secure
   cookies, container-flags/TLS/FDE manual section, posture document,
   health-disclosure check, error hygiene, DoS envelope, downgrade note.
   Feeds IQ its checklist items.
3. `m10-vnv-qualification` — V&V strategy doc, IQ/OQ tooling + record schema +
   reference environment, PQ protocol, VAL area, site qualification rendering.
   Depends on 1 (image to qualify) and 2 (checks to run).
4. `m10-audit-durability` — durable audit store (owner-queued follow-up).
5. `m10-pentest` — scope statement, seeded environment, remediation window,
   results-to-evidence flow. Scheduled once 1–3 land; PQ and pentest share the
   seeded environment.

The hardening sweep's decide-and-document items ride changes 2 and 5 rather
than forming their own change.

## Impact

New attack surface at implementation (FRG-PROC-006 per implementing change):
GHCR publishing and CI supply chain (registry credentials, action pinning,
provenance); headers middleware (low); doctor/qualification command (runs
against a live deployment); trusted-proxy handling (deliberate revision of the
X-Forwarded-For trust decision — misconfiguration risk documented). Site spec
gains a qualification-records requirement with build-failing cross-checks
(record version must match a tag, record SHA must match the tag's commit,
committed record must be a pass). Docs impact: new `docs/validation/`
tree, `docs/manual/` deployment-security section, threat-model and
risk-register deltas, commit-standard AREA table (VAL).

## Non-goals

- Bare-metal / non-Docker deployment support (explicitly unsupported, stated
  in the V&V strategy and manual).
- In-app TLS termination or certificate management.
- Full-database encryption (SQLCipher et al.) — rejected with rationale in
  the posture document.
- Bot/CI commits to main, in any form.
- Personal third-party credentials (Humble cookie, indexer keys, usenet
  accounts) in CI, in any form.
- Retro-qualification of 0.x releases (absence renders as absence).
- Mock-NNTP full-chain reference OQ — noted enhancement, not 1.0 scope; OQ v1
  stops at the SABnzbd contract boundary (paused-queue add/poll, no usenet
  backend).
- Publishing the raw pentest vendor report (summary of findings and
  remediations only; the report itself is an operator artifact).

## Approval

_Pre-design record only — decisions reviewed with Adrian in session 2026-07-15
(docker-only support; credentials-only at-rest + FDE recommendation;
operator/vendor record split; session-driven release with no CI commits; GHCR
via workflow token + fine-grained session PAT with feedback tooling;
fixtures-not-live-credentials in reference OQ; qualification records keyed to
commit + digest with the record outside the qualified configuration).
Implementation approval happens per implementing change at M10 kickoff
(FRG-PROC-009)._
