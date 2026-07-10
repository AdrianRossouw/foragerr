# known-anomalies — tasks

## 1. Register and seed entry

- [ ] 1.1 Create branch `change/known-anomalies`; allocate FRG-PROC-016 in
      `docs/traceability/requirements-registry.md` (FRG-PROC-002)
- [x] 1.2 Create `docs/security/known-anomalies.md` with the register format
      (required fields per FRG-PROC-016) and seed **KA-001**: exposed
      un-revocable ComicVine API key in public history — description,
      location (blob `495f29e`, all tags), impact evaluation, owner accept
      decision 2026-07-09 with rationale, mitigations, review triggers
      (FRG-PROC-016)
- [x] 1.3 Correct `docs/security/history-scan.md`: replace the blanket
      "no real credential has ever been committed" claim; add the KA-001
      finding to the disposition table (accepted, references KA-001); keep
      the zero-unresolved invariant accurate (FRG-PROC-015)
- [x] 1.4 Add RISK-042 to `docs/security/risk-register.md`: third-party use
      of the published key; accept with compensating mitigations; review
      triggers; cross-link KA-001 (FRG-PROC-006)

- [x] 1.5 Commit the removal of `docs/research/Foragerr.dc.html` from the
      working tree (owner decision: design handoff stays out of the repo; the
      historical blob remains, accepted per KA-001) (FRG-PROC-016)
- [x] 1.6 Record the owner's 2026-07-10 FRG-AUTH-008 direction on RISK-041:
      at-rest encryption key comes from the environment only, never a file;
      key rotation designed at the user-accounts milestone (FRG-PROC-006)

## 2. Scanner gap

- [x] 2.1 Add repo-root `.gitleaks.toml`: custom rule for 32+ char hex/base64
      literals assigned to bare `KEY`/token-ish identifiers; allowlist
      `backend/tests/**` fixtures and the rule's own test fixture; verify the
      gate re-scan now flags the KA-001 line shape and reports the existing
      11 dispositioned fixtures unchanged (FRG-PROC-015)
- [x] 2.2 Reference `.gitleaks.toml` from merge-gate checklist item 7 in
      `docs/process/commit-standard.md` (FRG-PROC-015)

## 3. Tests

- [x] 3.1 Tagged tests (FRG-PROC-016): register parses, KA IDs unique and
      well-formed, required fields present, KA-001 exists
- [x] 3.2 Tagged test (FRG-PROC-015): gitleaks with the repo config flags a
      synthetic fixture reproducing the KA-001 line shape (skip with notice
      when the gitleaks binary is unavailable)

## 4. Merge gate

- [ ] 4.1 Full merge-gate checklist; CHANGELOG entry + version bump; release
      notes reference KA-001 per FRG-PROC-016 (FRG-PROC-007, FRG-PROC-013)
- [ ] 4.2 Review cycle; sync delta to baseline; archive; registry flip;
      matrix; re-scan evidence; merge `--no-ff`, tag, release
