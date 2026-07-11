# Tasks — m4-add-new

## 1. Proposal and registry

- [x] 1.1 Branch `change/m4-add-new`; allocate FRG-META-015 in the registry;
      record approval (FRG-PROC-002, FRG-PROC-009)

## 2. Backend — ranking and add-option

- [x] 2.1 Relevance ordering of lookup + suggest candidates in the API layer:
      sort by (-name_similarity, year_distance, upstream_index); parity
      between endpoints; tests incl. closest-match-first, nothing-dropped,
      lookup/suggest parity, stable-order corpus cases
      (FRG-META-015, FRG-META-007)
- [x] 2.2 `SeriesCreate` optional `booktype` (vocabulary value or explicit
      "none"); `add_series()` persists it locked and skips derivation when
      present, derives as before when absent; API + flow tests
      (FRG-SER-005, FRG-SER-018)

## 3. Frontend — redesigned screen

- [x] 3.1 Rebuild AddSeries presentation to the design handoff: expandable
      result cards (cover, name, year, publisher, issue count, deck,
      In-library badge), API order untouched, inline add-config panel with
      monitor segmented control + collect-as segmented (default untouched =
      derivation); all outcome states preserved (FRG-UI-005)
- [x] 3.2 Rework `AddSeries.test.tsx`: every FRG-UI-005 scenario keeps a
      test; new tests for card rendering, collect-as payload mapping
      (untouched → no booktype; explicit → locked value), order-preservation
      (FRG-UI-005, FRG-PROC-004)

## 4. Docs and screenshots

- [x] 4.1 Rewrite `docs/manual/user/web-ui.md` §Adding a series (cards,
      ranked order, collect-as); check §Quick search wording (FRG-PROC-011)
- [x] 4.2 Refresh README tour shots via `tools/refresh-readme-shots.sh`
      against a dedicated clean instance (verify the tool spins its own —
      never :8790; fix here if not) (FRG-PROC-017)
- [x] 4.3 Registry header staleness rider: "Transmission" → qBittorrent
      (matches FRG-TOR-002) (FRG-PROC-002)

## 5. Sync, gate, release

- [x] 5.1 Sync meta/ser/ui deltas into main specs (FRG-PROC-003)
- [x] 5.2 Full suites green; matrix regenerated (no gaps); soup_check exit 0
      (FRG-PROC-004, FRG-PROC-005, FRG-PROC-012)
- [ ] 5.3 Tiered review gate — medium change: 4–5 angles + Codex full-diff;
      apply findings; re-evidence (FRG-PROC-007)
- [ ] 5.4 Merge `--no-ff`; tag v0.4.6 with CHANGELOG entry + pyproject bump
      landed on-branch BEFORE merge; push; gh release; archive change
      (FRG-PROC-007, FRG-PROC-013)
