# going-public — tasks

## 1. Registry, branch, and license

- [x] 1.1 Allocate FRG-PROC-014, FRG-PROC-015 (dev-process) and FRG-DEP-014 (dep)
      in `docs/traceability/requirements-registry.md`; create branch
      `change/going-public` (FRG-PROC-002)
- [x] 1.2 Add verbatim GPL-3.0 text as `LICENSE` at repo root; set the license
      declaration in `backend/pyproject.toml` (SPDX `GPL-3.0-or-later` if the
      toolchain accepts PEP 639, else classifier form per design Decision 1)
      (FRG-DEP-014)
- [x] 1.3 Tagged test for license consistency: `LICENSE` present and GPL-3.0,
      pyproject declaration matches, README names GPL-3.0 and links `LICENSE`
      (FRG-DEP-014)

## 2. Screenshots

- [ ] 2.1 Seed a demo library of public-domain comics (owner's PD holdings or
      Digital Comic Museum issues) and import it into a dev instance
      (FRG-PROC-014)
- [ ] 2.2 Write a Playwright capture script in `e2e/` producing deterministic,
      consistently-sized PNGs of the key screens (library grid, series detail,
      wanted/search, import, settings, OPDS-facing info) into
      `docs/readme-assets/` (≤ ~300 KB each) (FRG-PROC-014)
- [ ] 2.3 Commit the captured images and the script (FRG-PROC-014)

## 3. README rewrite

- [ ] 3.1 Rewrite README top matter: owned-library lead (import/rename, ComicVine
      metadata, OPDS reading), content-neutral acquisition description, no
      "not released publicly" paragraph (FRG-PROC-014)
- [ ] 3.2 Add the screenshot walkthrough: each major feature section embeds its
      image with a caption linking governing FRG ID(s) + spec section + manual
      page (design Decision 4 format) (FRG-PROC-014)
- [ ] 3.3 Add Roadmap section (Humble Bundle importer; loose/public-domain archive
      import — explicitly future work), license statement, and contribution
      posture (source-available personal tool and process demonstration; input
      not solicited) (FRG-PROC-014)
- [ ] 3.4 Tagged doc-consistency test: README image paths / caption FRG IDs /
      cited doc paths all resolve; no "not released publicly"/"private tool"
      self-description remains in README, CLAUDE.md, or docs/manual/index.md;
      Roadmap heading present (FRG-PROC-014)

## 4. Language sweep and risk rationales

- [ ] 4.1 Update `CLAUDE.md` and `docs/manual/index.md`: drop private/never-
      released framing, align intro with the new README lead (FRG-PROC-014,
      FRG-PROC-011 — manual impact: index intro wording only)
- [ ] 4.2 Reword RISK-015 and RISK-020 rationales in
      `docs/security/risk-register.md` to rest on the deployment posture
      (single-user, self-hosted, tailnet-scoped), noting repository visibility is
      not a compensating control; status/owner/review-triggers unchanged; sweep
      other "private tool" rationales for the same rewording (FRG-PROC-014)

## 5. History hygiene gate

- [ ] 5.1 Run gitleaks across full history (all refs); record evidence below
      (tool + version, scanned HEAD, refs, finding count, dispositions)
      (FRG-PROC-015)
- [ ] 5.2 Review published release notes v0.1.0..v0.3.3 for anything unsuitable
      for public view; record the outcome (FRG-PROC-015)
- [ ] 5.3 Tagged test asserting the evidence record exists and names the scanned
      HEAD commit (FRG-PROC-015)

## 6. Merge gate and flip

- [ ] 6.1 Full merge-gate checklist (suite green, soup_check exit 0, traceability
      regenerated, CHANGELOG + version bump, release notes) per
      `docs/process/commit-standard.md` (FRG-PROC-007, FRG-PROC-013)
- [ ] 6.2 Pre-merge review cycle (/code-review + /simplify) on the branch
- [ ] 6.3 Merge `--no-ff` to main, tag, publish GitHub Release
- [ ] 6.4 **Owner action**: flip repository visibility to public on GitHub;
      optionally update repo description/topics to match the new lead
      (FRG-PROC-015 gate must be green first)

## Evidence

*(filled at gate time — gitleaks output summary and release-notes review outcome)*
