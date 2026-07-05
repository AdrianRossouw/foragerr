# Tasks

## 1. Spec and registry (FRG-PROC-011, FRG-PROC-012)

- [x] 1.1 Register FRG-PROC-011 and FRG-PROC-012 in the requirements registry
      (`proposed`, milestone `—`)
- [x] 1.2 Author the dev-process spec delta with both requirements and scenarios

## 2. Manual + labelling creation — backfill (FRG-PROC-011)

- [x] 2.1 Create `docs/manual/` structure: `index.md`, user guide, admin guide
- [x] 2.2 User guide backfill for behavior merged to `main` at backfill time: library &
      series management, metadata refresh, search & indexers, downloads (SABnzbd + DDL);
      `user/import.md` is a deliberate stub — filled at the m1-import-pipeline merge
      gate (first live exercise of the sync rule), renaming documented with it
- [x] 2.3 Admin guide backfill: deployment (explicitly marked forthcoming until change
      7 ships the Dockerfile), configuration (`/config/config.yaml`, `FORAGERR_*` env
      precedence), secrets handling, network exposure (Tailscale-only posture, no M1
      auth as accepted RISK-020)
- [x] 2.4 Create root `README.md` labelling: project purpose, security & regulatory
      posture (pointer to `docs/security/`), way of working (dev-process summary,
      pointer to `openspec/` + `docs/process/`), installation placeholder pointing at
      the admin guide (full install section deferred until after change 7)

## 3. SOUP register (FRG-PROC-012)

- [ ] 3.1 Create `docs/security/soup-register.md`: runtime table (name, version
      constraint, source, purpose, supporting requirements/subsystems, license,
      anomaly-review note) + lighter dev/test tools section
- [ ] 3.2 Backfill from current `backend/pyproject.toml` and `frontend/package.json`,
      with a dated initial anomaly review per runtime item
- [ ] 3.3 Implement `tools/soup_check.py`: parse direct deps from both manifests,
      verify one-to-one register rows + version-constraint match, exit non-zero on
      drift; document invocation beside `trace.py` in the gate checklist

## 4. Process wiring (FRG-PROC-011, FRG-PROC-012)

- [ ] 4.1 Add the manual-sync and SOUP rules to `CLAUDE.md` non-negotiable process rules
- [ ] 4.2 Add manual-impact declaration + SOUP check to the merge-gate checklist in
      `docs/process/` docs
- [ ] 4.3 Add decision-index rows in `docs/process/decisions.md` (manual-sync + SOUP
      adoption; change-8 acceptance-report decision)

## 5. Merge gate

- [ ] 5.1 Suite green + `tools/soup_check.py` exit 0 + `tools/trace.py` exit 0 →
      review → `--no-ff` merge → archive → delete branch
