# m11-acquisition-responsiveness — tasks

## 1. Registry + budgeted interactive search

- [ ] 1.1 Allocate FRG-SRCH-015, FRG-SCHED-012, FRG-DL-015, FRG-UI-041
      (approved/M11); note MODIFIED FRG-SRCH-014, FRG-API-008,
      FRG-SER-005 (FRG-PROC-002)
- [ ] 1.2 Budgeted fan-out: per-indexer deadline via asyncio.wait on the
      interactive path only; clean cancellation between politeness
      waits; timed_out outcome on IndexerSearchOutcome; config
      indexer_search_time_budget_seconds (20, clamp 5-60)
      (FRG-SRCH-015, FRG-SRCH-014)
- [ ] 1.3 Release response additive per-indexer outcomes field
      (FRG-API-008)
- [ ] 1.4 Tests: slow-indexer partial return within budget, timeout
      outcome shape, backoff bookkeeping uncorrupted by cancellation,
      backlog path unbudgeted, cache/grab of partial sets, listener
      guard headroom (FRG-SRCH-015, FRG-SRCH-014, FRG-API-008)

## 2. Sweeps + next-search surface

- [ ] 2.1 Default mini-sweep: unconditional series-search enqueue for
      monitored adds w/ wanted issues; no-wanted adds stay quiet;
      checkbox semantics preserved; dedup pins (FRG-SER-005)
- [ ] 2.2 First-enabled-indexer trigger (count 0→1) enqueues one
      backlog-search (FRG-SCHED-012)
- [ ] 2.3 Wanted screen next-automatic-search line from the scheduled
      task resource (FRG-SCHED-012)
- [ ] 2.4 Tests: default sweep fires/quiet cases, checkbox dedup,
      0→1 trigger + no re-fire, wanted next-run render
      (FRG-SER-005, FRG-SCHED-012)

## 3. Visibility-stall escalation

- [ ] 3.1 Migration 0028 (import_stall_count, first_stalled_at);
      increment at the drain's no-importable-files branch; reset on
      success/new evidence; survives the tracking ping-pong
      (FRG-DL-015)
- [ ] 3.2 Downloads health component past
      import_stall_threshold_cycles (default 5, clamp >=2), aggregated,
      mount/path remediation (FRG-DL-015)
- [ ] 3.3 Tests: repeated reconcile+drain cycles against an invisible
      path accrue count through the ping-pong (the untested loop),
      threshold degrade + clear, reset on success, migration chain
      (FRG-DL-015)

## 4. UI + client priority

- [ ] 4.1 Search results per-indexer outcome strip, quiet all-searched
      form (FRG-UI-041)
- [ ] 4.2 downloadClientKind priority row-field + content-level test
      pinning BOTH provider kinds' priority (FRG-UI-009 truth fix)
- [ ] 4.3 Frontend tests: strip states, wanted next-run, client
      priority form render/save (FRG-UI-041, FRG-UI-009)

## 5. Docs, gate, release

- [ ] 5.1 Manual: search page (budget/partial/outcomes), library-add
      (default sweep), admin configuration (budget + stall threshold
      settings), downloads (client priority) (FRG-PROC-011)
- [ ] 5.2 Matrix regen; trace/soup/risk green (FRG-PROC-005)
- [ ] 5.3 Medium gate: concurrency angle on cancellation + fan-out,
      state angle on stall memory, conformance angle; Codex; simplify
      pass; e2e (FRG-PROC-004)
- [ ] 5.4 Rig verification: real interactive search returns partial
      under the default listener guard (retire the 120s band-aid in
      rig config), stall memory on a synthetic invisible path,
      default sweep on a fresh add
- [ ] 5.5 Archive/sync, registry flip, release v0.13.0 per /release
      (FRG-PROC-013)
