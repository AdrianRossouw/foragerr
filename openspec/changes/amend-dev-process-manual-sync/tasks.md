# Tasks

## 1. Spec and registry (FRG-PROC-011)

- [x] 1.1 Register FRG-PROC-011 in the requirements registry (`proposed`, milestone `—`)
- [x] 1.2 Author the dev-process spec delta with the requirement and scenarios

## 2. Manual creation — backfill (FRG-PROC-011)

- [ ] 2.1 Create `docs/manual/` structure: `index.md`, user guide, admin guide
- [ ] 2.2 User guide backfill for behavior merged to `main` at backfill time: library &
      series management, metadata refresh, search & indexers, downloads (SABnzbd + DDL),
      import pipeline & renaming
- [ ] 2.3 Admin guide backfill: deployment (Docker, linuxserver.io conventions, port
      8789), configuration (`/config/config.yaml`, `FORAGERR_*` env precedence),
      secrets handling, network exposure (Tailscale-only posture, no M1 auth)

## 3. Process wiring (FRG-PROC-011)

- [ ] 3.1 Add the manual-sync rule to `CLAUDE.md` non-negotiable process rules
- [ ] 3.2 Add manual-impact declaration + gate check to the merge-gate checklist in
      `docs/process/` docs
- [ ] 3.3 Add decision-index rows in `docs/process/decisions.md` (manual-sync adoption;
      change-8 acceptance-report decision)

## 4. Merge gate

- [ ] 4.1 Suite green (docs-only change — full suite run to confirm no accidental
      code impact) → review → `--no-ff` merge → archive → delete branch
