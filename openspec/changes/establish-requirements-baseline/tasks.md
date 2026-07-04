# Tasks

## 1. Baseline synthesis (FRG-PROC-002, FRG-PROC-003)

- [x] 1.1 Five domain drafting passes over the Phase 1 research (read-only agents)
- [x] 1.2 Allocate FRG IDs in draft order; generate 20 capability specs
- [x] 1.3 Dedup pass: single owners for wanted-derivation (SER), blocklist loop (DL);
      withdraw FRG-PP-015 as duplicate
- [x] 1.4 Regenerate registry with Status + Milestone columns
- [x] 1.5 `openspec validate --all` green

## 2. Traceability tooling (FRG-PROC-005)

- [x] 2.1 `tools/trace.py` + generated `docs/traceability/matrix.md`, zero gaps

## 3. Security analysis (FRG-PROC-006)

- [ ] 3.1 STRIDE threat model over all components → `docs/security/threat-model.md`
- [ ] 3.2 Risk register with every research security flag → `docs/security/risk-register.md`
- [ ] 3.3 SEC-area requirements for uncovered gaps; register + spec them

## 4. Review and approval (FRG-PROC-009)

- [ ] 4.1 Completeness-critic pass (capability-map coverage, risk coverage, duplicates,
      registry↔spec consistency); fix findings
- [ ] 4.2 Owner approval recorded; registry rows `proposed` → `approved`; archive change;
      merge to main
