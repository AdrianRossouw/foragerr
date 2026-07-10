# roadmap-reshape — tasks

## 1. Registry and specs

- [x] 1.1 Create branch `change/roadmap-reshape`; rewrite the registry
      milestone legend (M4 design refresh · M5 creators & follows · M6
      sources · M7 torrents · M8 authentication; dated owner approval +
      grant boundary) (FRG-PROC-002)
- [x] 1.2 Move registry rows: FRG-UI-018, FRG-PULL-007..009 → M4;
      FRG-AUTH-008 → M6; FRG-TOR-001..006, FRG-IDX-012 → M7;
      FRG-AUTH-002..007/009/010, FRG-SEC-005 → M8 (FRG-PROC-002)
- [x] 1.3 Update matching `Milestone:` bullets in baseline specs (ui, pull,
      auth, tor, idx, sec); `tools/trace.py` exits 0 with no milestone drift
      (FRG-PROC-005)

## 2. Process docs

- [x] 2.1 Add `CRTR` (Creators & follows) to the AREA table in
      `docs/process/commit-standard.md` (FRG-PROC-001)
- [x] 2.2 Amend merge-gate checklist item 6: the review cycle includes an
      independent-model (Codex) full-diff ninth perspective (FRG-PROC-007)

## 3. Risk posture

- [x] 3.1 RISK-020: record the owner's 2026-07-10 re-acceptance of no-auth
      through M7 (public codebase; Tailscale-only posture and review
      triggers unchanged) (FRG-PROC-006)

## 4. Merge gate

- [x] 4.1 Merge-gate checklist (suites, soup, trace, config re-scan +
      evidence, CHANGELOG v0.3.7 + bump, release notes) (FRG-PROC-007,
      FRG-PROC-013, FRG-PROC-015)
- [x] 4.2 Review cycle (proportionate + Codex ninth); archive; merge
      `--no-ff`; tag; push; release
