# site-regulated-story — tasks

## 1. Registration & governance

- [x] 1.1 Registry hygiene: FRG-SITE-001..006 and the SITE AREA row were allocated
      at proposal time; flip rows `proposed` → `approved` once the owner records
      approval, and `approved` → `implemented` at the merge gate [FRG-SITE-001..006]
- [x] 1.2 docs/security updates: risk-register entry for the GitHub Actions
      workflow (supply chain, token scope) and threat-model note that the site is
      static output with no listener/input/credentials; record the four pinned
      GitHub actions in `docs/security/soup-register.md` [FRG-SITE-005]

## 2. Generator

- [x] 2.1 `site/build.py` skeleton: artifact loaders for registry, matrix,
      CHANGELOG, risk register, LICENSE, git tags — each failing the build with a
      named error on missing/unparseable input; `--out` dir; no partial output
      [FRG-SITE-001]
- [x] 2.2 Derived data: requirement/release/milestone counts, traced-test coverage
      (N of M), timeline model (CHANGELOG entries × tags, grouped by minor),
      trust-center artifact index (existence-checked), risk table model,
      exemplar trace-card row resolved from `site/site.toml` [FRG-SITE-001,
      FRG-SITE-003, FRG-SITE-004]
- [x] 2.3 Templates for the five pages ported from the design (hero A + trace
      card, stat strip, method lifecycle + pillars + "How to weigh this" callout,
      timeline, trust center, product) with `string.Template` slots;
      `site/static/site.css` token port (app font stacks, no font files — see
      design.md decision 3); README screenshots copied at build [FRG-SITE-002]
- [x] 2.4 Truthfulness scans in the build: banned-phrase list
      (`site/banned_phrases.txt`) enforced over built HTML; license/footer/repo-URL
      assertions [FRG-SITE-006, FRG-SITE-004]

## 3. Tests (tagged per requirement)

- [x] 3.1 Generator unit tests against fixture artifacts: fact-tracking and
      fail-on-missing [`@pytest.mark.req("FRG-SITE-001")`], five pages + nav +
      honesty callout + real trace card [FRG-SITE-002], timeline mirrors CHANGELOG
      and fails on untagged version [FRG-SITE-003], trust-center existence checks +
      coverage metric + no-nonexistent-evidence scan [FRG-SITE-004], banned-phrase
      and license/link assertions [FRG-SITE-006]
- [x] 3.2 Workflow lint test: parse `.github/workflows/pages.yml`, assert SHA-pinned
      `uses:` and exact least-privilege permissions
      [`@pytest.mark.req("FRG-SITE-005")`]

## 4. Deployment & docs

- [x] 4.1 `.github/workflows/pages.yml` (push to main + workflow_dispatch; build →
      upload-pages-artifact → deploy-pages; SHA-pinned; `contents: read`,
      `pages: write`, `id-token: write`) [FRG-SITE-005]
- [x] 4.2 README: add site link under the header block; verify no manual pages are
      affected (manual impact: none — declared in proposal) [FRG-SITE-006]
- [x] 4.3 Local end-to-end verify: build site from the real repo, open output,
      spot-check every displayed fact against its source artifact; run full suite +
      trace.py + soup_check + risk_register_check [FRG-SITE-001..006]

## 5. Post-merge (owner + orchestrator)

- [ ] 5.1 Owner: flip repo Settings → Pages → Source to "GitHub Actions"
- [ ] 5.2 Verify first deploy: workflow green, adrianrossouw.github.io/foragerr
      serves the built site, artifact links resolve [FRG-SITE-005]

## 6. Preview feedback round 1 (2026-07-15, owner-approved amendment)

- [x] 6.1 Trust Center "Process & governance" cards: dev-process spec, commit
      standard, archived changes w/ derived approval count, manual, history
      scan — existence-checked [FRG-SITE-004]
- [x] 6.2 Coverage-by-status panel (implemented N/N tested, approved backlog,
      process rules tested vs hook-enforced) derived from the matrix
      [FRG-SITE-004]
- [x] 6.3 "Not in place yet" absence section (pentest, CI gates, advisory
      review, CAPA) each citing its committed deferral doc; banned-phrase scan
      carve-out for the single data-absence section; spec delta amended
      [FRG-SITE-004, FRG-SITE-006]

## 7. Merge-gate review fixes (2026-07-15, 8-angle fleet + Codex)

- [x] 7.1 SVG logo referenced as <img> (never inlined) + build-time script/handler
      assertion — closes stored-XSS path [FRG-SITE-002]
- [x] 7.2 Matrix pollution fixed: fixtures use synthetic IDs + fixture site.toml
      via build(config_dir=...); real FRG-SER-019 no longer mis-attributed to the
      site tests [FRG-SITE-002]
- [x] 7.3 Two-tier banned-phrase scan (positioning everywhere; evidence-claim in
      authored copy only, exempting the absence section and data-generated
      source passthrough); non-nesting marked-region regex; spec + tests updated
      [FRG-SITE-004, FRG-SITE-006]
- [x] 7.4 CHANGELOG parser handles code fences (<pre>) and fails loudly on a
      malformed release heading; blank matrix Tests cell no longer counted as
      tested [FRG-SITE-001, FRG-SITE-003, FRG-SITE-004]
- [x] 7.5 Process-rule coverage tile guarded (fails if a non-PROC row is `active`);
      dead coverage() removed; shared table-row parser; archive fails on a
      missing proposal.md; --out delete-guard; sources.png caption matches README
      [FRG-SITE-004]
- [x] 7.6 Workflow concurrency cancel-in-progress:false; trace.py named
      PRE_BASELINE_STATUSES + regression test pinning the approved-in-open-delta
      allowance [FRG-SITE-005, FRG-PROC-005]
