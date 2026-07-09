# going-public — design

## Context

foragerr's repository has been private since inception; README, CLAUDE.md, the
manual, and several risk-register rationales lean on that. The owner has decided to
open the repository — not to attract users or contributors, but to stop doing the
work privately, and to make the regulated-development demonstration inspectable.
Constraints: the deployment posture (single-user, no auth, Tailscale-only) does not
change; no new features ship in this change; the README leads with the
owned-library story and stays content-neutral about acquisition; preferred gate
size is one medium change.

Current state, verified: no `.env` ever committed; a keyword sweep of history finds
no hardcoded credentials; `sample-comics/` (38 GB of real comics) is gitignored and
absent from history; `docs/research/Foragerr.dc.html` (owner's design export) *is*
tracked and becomes public — kept deliberately (owner decision 2026-07-09): it
shows how the product was designed and stays useful for future design review.
There is no `LICENSE`
file. Releases v0.1.0..v0.3.3 already exist as GitHub Releases and become visible
at flip time.

## Goals / Non-Goals

**Goals**: honest public labelling (FRG-PROC-014), GPL-3.0 licensing
(FRG-DEP-014), evidence-backed history hygiene (FRG-PROC-015), screenshot
walkthrough tying UI → requirement IDs → specs/manual, "private" language sweep,
risk-rationale rewording.

**Non-goals**: see proposal — no code, no features, no posture change, no
community infrastructure, no relicensing of history.

## Decisions

1. **License = GPL-3.0** (owner decision 2026-07-09). Matches Sonarr/Radarr/Mylar3,
   the ecosystem foragerr studies (`.reference/`, `docs/research/` findings derive
   from GPL code), so it is also the conservative choice. Alternatives: AGPL-3.0
   (network clause buys nothing for a no-adoption project), MIT (sits oddly against
   GPL-derived research), no license (hostile default). `pyproject.toml` gets
   `license = "GPL-3.0-or-later"` (SPDX expression, PEP 639 style — verify the
   packaging toolchain accepts it; fall back to classifier form if not).

2. **Screenshots from public-domain content only.** The demo library for capture is
   seeded with public-domain comics (e.g. Digital Comic Museum scans already in the
   owner's collection, or freshly fetched PD issues), never the real library — PD
   covers are redistributable in-repo and keep the screenshots consistent with the
   owned-library story. Capture mechanism: reuse the existing Playwright e2e harness (`e2e/`) pointed at
   a dev instance with the demo library imported; a small capture script produces
   deterministic, consistently-sized PNGs. Alternative (manual screenshots)
   rejected: not reproducible, inconsistent sizing/theme.

3. **Screenshot storage: `docs/readme-assets/` committed to the repo.** Sizes kept
   modest (≤ ~300 KB each, ~6–8 images) so the clone stays light. Alternatives:
   GitHub-hosted user-images URLs (fragile, not reviewable in-change), git-lfs
   (infrastructure for megabytes we don't need).

4. **Caption→traceability linking format.** Each screenshot caption is a one-liner:
   `*Screen — governed by [FRG-UI-00x](docs/traceability/requirements-registry.md),
   spec: [ui](openspec/specs/ui/spec.md), manual:
   [library](docs/manual/user/library.md)*`. A tagged doc-consistency test
   (FRG-PROC-014) parses README image references and captions and asserts every
   image path, FRG ID, and doc path resolves — same style as the existing
   doc-consistency tests.

5. **History scan = gitleaks, run at gate time, evidence in the change.** gitleaks
   binary is installed ad hoc for the gate (dev-time tool, not runtime SOUP — no
   register entry; the same reasoning as other dev tooling, noted in the proposal).
   Full `git log --all` range scanned; output summary (tool version, HEAD, refs,
   finding count, dispositions) recorded in `openspec/changes/going-public/`
   evidence section of tasks.md (and referenced from the merge-gate checklist run).
   The FRG-PROC-015 tagged test asserts the evidence record exists and names a
   commit that is an ancestor-or-equal of the flip; the *scan itself* is a gate
   step, not a unit test (network/tooling dependency).

6. **Risk rationales reworded, not re-decided.** RISK-015 and RISK-020 rationales
   currently say "single-user private tool"; they are reworded to "single-user,
   self-hosted, tailnet-scoped deployment" with an added note that repository
   visibility is not a compensating control. Accepted status, owners, and review
   triggers unchanged. If the re-read surfaces a real posture problem, it is
   escalated to the owner as a separate proposal, not folded in.

7. **README information architecture.** Order: what it is (owned-library story) →
   screenshots walkthrough → security & regulatory posture (kept, it is the
   showcase) → way of working → installation → roadmap → license & posture footer.
   The existing "Security & regulatory posture" and "Way of working" sections
   survive nearly as-is; the rewrite concentrates on the top matter and the new
   walkthrough/roadmap/license/posture sections.

## Risks / Trade-offs

- [Public README promises traceability; a reader finds a broken link] → the
  FRG-PROC-014 doc-consistency test makes link rot a test failure, not an
  embarrassment.
- [Screenshots go stale as the UI evolves] → accepted: they are illustrative, not
  controlled UI documentation; the capture script is committed so refresh is one
  command. Staleness does not violate FRG-PROC-014 (claims are about capability,
  not pixels).
- [Something sensitive lurks in history despite the keyword sweep] → gitleaks
  full-history gate (FRG-PROC-015) before flip; if a finding appears, flip blocks
  until the secret is revoked (scenario: Finding blocks the flip).
- [Release notes v0.1.0..v0.3.3 become public retroactively] → reviewed once as a
  gate item; they are Conventional-Commits derived and were written key-free.
- [GPL obligations on a repo mixing docs and code] → GPL-3.0 applied repo-wide via
  root LICENSE; no per-file headers (out of proportion for this project size —
  recorded as a deliberate omission).

## Migration Plan

No deployment migration — docs-only. Sequence: branch `change/going-public` →
implement → merge gate (full suite + soup_check + gitleaks evidence) → merge to
main → tag per FRG-PROC-013 → owner flips visibility on GitHub (manual, final) →
owner optionally updates repo description/topics.

Rollback: flip the repository back to private (owner action); revert commit if
labelling must be withdrawn. History cannot be un-published once cloned — hence
the pre-flip gate ordering.

## Open Questions

- Exact public-domain issues to seed the demo library (owner may have favorites;
  otherwise implementer picks well-known PD titles from Digital Comic Museum).
- Whether `pyproject.toml`'s toolchain accepts SPDX `license` strings (PEP 639) —
  resolved during implementation, classifier fallback specified in Decision 1.
