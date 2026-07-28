# m11-acquisition-responsiveness — the machine reacts like a person would

## Why

Four rig findings share one theme: the machine has the information and
sits on it. A fresh install downloads nothing until the six-hour backlog
tick (finding #2); an interactive search waits for the slowest indexer
until the listener's 30s guard kills the whole request — observed 76s+
on real indexers, band-aided on the rig with a 120s listener timeout
that must become unnecessary (finding #3); a completed download whose
files the importer cannot see ping-pongs between ok and blocked every
minute forever with no escalation (finding #1, the Die Loaded stall);
and the download-client form omits the priority field the spec already
promises (finding #5's surviving half — the indexer field has been in
the UI since 2026-07-05; FRG-UI-009's scenario claims the client form
renders priority and is currently false against the implementation).

## What Changes

- **Per-indexer interactive time budget with partial results** (new
  `FRG-SRCH-015`; MODIFIED `FRG-SRCH-014`, `FRG-API-008` — complete
  restatements): the interactive fan-out gives each indexer a bounded
  time budget; results from indexers that finished are returned when
  the budget lapses, and each slow indexer is reported as an honest
  per-indexer timed-out outcome on the response (riding the existing
  IndexerSearchOutcome failure shape). Total interactive latency stays
  under the default listener guard — the rig's 120s band-aid retires.
- **Mini-sweep on add, by default** (MODIFIED `FRG-SER-005`; new
  `FRG-SCHED-012`): adding a monitored series triggers the existing
  bounded per-series search (the search-on-add chain) without requiring
  the checkbox — the checkbox becomes "also search unmonitored gaps"
  semantics preserved exactly as spec'd today, with the default sweep
  bounded to the newly added series' wanted issues. Configuring the
  FIRST enabled indexer triggers one bounded sweep of wanted issues
  (the fresh-install case: indexers usually arrive after series).
  "Next automatic search at …" surfaces contextually on the Wanted
  screen (data already exists on the Tasks surface).
- **Visibility-stall escalation** (new `FRG-DL-015`): a tracked
  download that keeps completing-then-blocking with no importable files
  accrues a consecutive-stall memory (migration 0028); past a bounded
  threshold, application health degrades with an actionable message
  (path/mount guidance) while the queue row keeps its honest per-cycle
  state. The ping-pong retry-on-evidence design stays — the escalation
  is additive memory, not a behavior change to import retries.
- **Download-client priority field** (bug-class truth fix under
  existing `FRG-UI-009`): the client form's row fields gain the numeric
  priority the requirement's scenario already asserts; a content-level
  test pins both provider forms' priority fields so the audit can't
  pass vacuously again.
- **Per-indexer outcome surface** (new `FRG-UI-041`): the interactive
  search results panel shows per-indexer outcomes — searched, timed
  out (with the budget), failed, backing off — so a partial result is
  visibly partial, never silently smaller.

## Capabilities

### New Capabilities

None — extensions of existing areas.

### Modified Capabilities

- `srch`: ADDED FRG-SRCH-015 (per-indexer budget + partial results);
  MODIFIED FRG-SRCH-014 (interactive search; complete restatement).
- `api`: MODIFIED FRG-API-008 (release endpoint carries per-indexer
  outcomes incl. timeouts; complete restatement).
- `ser`: MODIFIED FRG-SER-005 (default mini-sweep on add; the
  "inert stub until change 4" scenario wording reconciled; complete
  restatement).
- `sched`: ADDED FRG-SCHED-012 (first-indexer-configured sweep +
  contextual next-search surfacing).
- `dl`: ADDED FRG-DL-015 (visibility-stall memory + health
  escalation).
- `ui`: ADDED FRG-UI-041 (per-indexer outcome display); FRG-UI-009's
  client-priority scenario becomes true (bug-class, no delta needed —
  recorded here for traceability).

## Impact

- Backend: search_ops/pipeline.py (budgeted fan-out via asyncio.wait
  with per-indexer deadline), indexers/service.py (outcome shape),
  api/release.py (outcome resource), library/flows/refresh.py +
  api/indexers.py (sweep triggers), downloads/{tracking,imports,
  models}.py + migration 0028 (stall memory), health/service.py
  (downloads component), config.py (per-indexer budget setting,
  default sized so budget × politeness stays under the listener
  guard).
- Frontend: release search results outcomes strip, Wanted screen
  next-search line, providerKinds downloadClient priority field.
- No dependency changes. No new attack surface: no new listener,
  parser, or egress — the outcome surface is data already held,
  the sweep triggers reuse existing commands under existing auth.
  Rationale per FRG-PROC-006.
- Manual impact (FRG-PROC-011): user search page (partial results +
  outcomes), user library/add page (default sweep), admin
  configuration (budget setting, stall threshold), downloads page
  (client priority).

## Non-goals

- Async search-job-and-poll redesign (the bounded-budget shape keeps
  the synchronous contract; a job model is a different change if ever).
- Remote path mappings (Sonarr-style) — the health escalation names
  the class of fix; the mapping feature remains future work.
- Backlog cadence changes (the 6h tick stands; the sweep covers the
  gap it leaves at add-time).
- Any change to grab/decision logic or the comparator.

## Approval

Proposed under the M11 standing grant (owner approval 2026-07-27,
recorded in the m11-import-intelligence pre-design's Approval section,
commit 562b16f). One default changes: search-on-add's bounded sweep
runs for newly added monitored series without the checkbox. This is
acquisition of explicitly monitored content the operator just added —
the add action itself is the intent — and the pre-design names this
exact fix shape ("mini-sweep on series-add"); it is called out here
under the intent-presuming-defaults rule rather than assumed silently,
with the owner's hard-stop review at milestone close as the checkpoint.
