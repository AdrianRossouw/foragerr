# Tasks — roadmap-single-source

## 1. Registry and branch

- [ ] 1.1 Create branch `process/roadmap-single-source`; allocate FRG-PROC-018
      ("Roadmap single source of truth", dev-process, active) in
      `docs/traceability/requirements-registry.md` (FRG-PROC-002, FRG-PROC-018)

## 2. Roadmap document (corrective)

- [ ] 2.1 Write `docs/roadmap.md`: entries for remaining M4 work (pull screen,
      FRG-UI-018 + FRG-PULL-007..009), M5 creators, M6 sources (credential
      store, Humble importer, archive.org), M7 torrents, M8 authentication —
      milestone + description + allocated ids per entry, including the Humble
      importer and public-domain archive import as future work (FRG-PROC-018,
      FRG-PROC-014)
- [ ] 2.2 Shrink `README.md` Roadmap section to a pointer at `docs/roadmap.md`
      (heading retained), removing the stale M4 design-refresh entry
      (FRG-PROC-014, FRG-PROC-018)
- [ ] 2.3 Sweep `docs/manual/**` for forward references (start:
      `admin/network.md` "no auth before M8"; grep for M5–M9 tokens and
      planned-phrasing markers); replace restatements with links to
      `docs/roadmap.md` (FRG-PROC-011, FRG-PROC-018)

## 3. Merge-gate checks (preventive)

- [ ] 3.1 Add `backend/tests/test_roadmap_consistency.py` tagged
      `@pytest.mark.req("FRG-PROC-018")`: containment check (M5–M9 word-boundary
      tokens + planned-phrasing markers over `README.md` and `docs/manual/**`,
      file+token allowlist with justification comments) (FRG-PROC-018)
- [ ] 3.2 Same module: freshness check — parse `FRG-*` ids from
      `docs/roadmap.md`, fail on `implemented` status or unknown id in the
      requirements registry (FRG-PROC-018)
- [ ] 3.3 Retarget `backend/tests/test_public_labelling.py` roadmap assertions:
      README Roadmap heading links to `docs/roadmap.md`; Humble/archive
      future-work assertion moves to `docs/roadmap.md` (FRG-PROC-014)

## 4. Spec sync and gate

- [ ] 4.1 Sync the dev-process delta into `openspec/specs/dev-process/spec.md`
      (FRG-PROC-018 added, FRG-PROC-014 modified) (FRG-PROC-003)
- [ ] 4.2 Full suite green; regenerate traceability matrix (`tools/trace.py`);
      `tools/soup_check.py` exit 0 (no dependency changes expected); merge-gate
      checklist per `docs/process/commit-standard.md` (FRG-PROC-004,
      FRG-PROC-005, FRG-PROC-012)
- [ ] 4.3 Tiered review gate — small change: 2–3 angles + Codex full-diff
      review; then `--no-ff` merge to `main`, delete branch, archive change
      (FRG-PROC-007)
