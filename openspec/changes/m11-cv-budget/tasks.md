# m11-cv-budget — tasks

## 1. Registry and gate lanes (FRG-META-022, FRG-META-016)

- [ ] 1.1 Allocate FRG-META-022, FRG-SRC-013, FRG-API-025, FRG-UI-040
      (approved/M11); note MODIFIED FRG-META-016 (FRG-PROC-002)
- [ ] 1.2 Lane dimension on the gate: acquire(lane=), batch default,
      batch share config (0.70, clamp 0.30-0.95), one ledger with
      lane-tagged stamps, refusal names the lane (FRG-META-022)
- [ ] 1.3 Lane threading at the client seam: ComicVineClient(lane=),
      covers batch, enrich/refresh/creators/bibliography batch;
      api factory/_operator_cv_client/library-import/test interactive
      (FRG-META-022)
- [ ] 1.4 Tests: batch-pauses-first w/ interactive reserve, interactive
      full-ceiling honesty, unclassified=batch, one-key non-goal pin,
      FRG-META-016 non-regression suite green (FRG-META-022)

## 2. Health + meter (FRG-META-016, FRG-API-025, FRG-UI-040)

- [ ] 2.1 Approaching-limit health state from the existing 80% data,
      independent dimension, names bucket/usage/paused lane
      (FRG-META-016)
- [ ] 2.2 SystemHealthComponent additive detail w/ budget numbers;
      unauthenticated surface unchanged (FRG-API-025)
- [ ] 2.3 Settings General full meter; Sources compact above-fraction
      indicator; lookup outcome note carries the typed resume message
      (FRG-UI-040)
- [ ] 2.4 Tests: approaching-state appears/clears, detail shape +
      no-unauth-leak, meter render states, outcome-note fidelity
      (FRG-META-016, FRG-API-025, FRG-UI-040)

## 3. Enrichment frugality + recompute (FRG-SRC-013)

- [ ] 3.1 Migration 0027 proposal_attempted_at; stamp on touch; pending
      order NULLs-first-then-oldest; CV-error re-attempt spacing
      (config, operator paths exempt) (FRG-SRC-013)
- [ ] 3.2 Bulk recompute command + POST /sources/{id}/recompute-
      proposals (pre-universe shape + opt-in markers; batch lane;
      resumable; new-rows-only) + marker eligibility on key
      configuration (FRG-SRC-013)
- [ ] 3.3 Tests: head-cannot-starve-tail, spacing w/ operator exemption,
      resumable recompute across budget refusal, decisions untouched,
      key-transition eligibility, FRG-SRC-010 deferral invariant
      non-regression (FRG-SRC-013)

## 4. Docs, gate, release

- [ ] 4.1 Manual: admin configuration (lanes/share/spacing settings),
      sources page (meter, recompute); ratelimit docstring correction
      (FRG-PROC-011)
- [ ] 4.2 Matrix regen; trace/soup/risk green (FRG-PROC-005)
- [ ] 4.3 Medium-tier gate (early Codex after first implementation
      commit + delta at close; concurrency angle on the gate lanes) +
      e2e (FRG-PROC-004)
- [ ] 4.4 Live rig verification: meter renders real usage, recompute
      refreshes a stale pre-v0.11 proposal batch, approaching warning
      at real spend
- [ ] 4.5 Archive/sync specs, registry flip, release v0.12.0 per
      /release (FRG-PROC-013)
