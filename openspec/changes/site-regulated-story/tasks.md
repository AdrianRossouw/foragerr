# site-regulated-story — tasks

## 1. Registration & governance

- [ ] 1.1 Registry hygiene: FRG-SITE-001..006 and the SITE AREA row were allocated
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
