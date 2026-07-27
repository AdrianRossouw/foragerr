# m11-import-intelligence — milestone pre-design (decomposition for owner review)

## Why

Between 2026-07-20 and 2026-07-27 the owner drove a live rig (real
indexers, real SABnzbd, a real 1,318-item Humble collection) and produced
**21 recorded findings**. They cluster tightly: matching that ignores
knowledge the system already has; state that goes stale or hides; a
metadata budget spent carelessly; review surfaces that don't scale past a
dozen rows; a discovery calendar you can't act on. That cluster is a
coherent capability — the **intelligence layer between "bytes acquired"
and "correctly filed, discoverable, readable"** — and the owner declared
it a milestone (2026-07-27). This record is the reviewable decomposition;
it is NOT apply-ready by intent and allocates no requirement ids
(registry lesson: ids belong to each implementing change's proposal).

## Proposed 1.0 sequence (owner decision pending)

M11 (this) → m10-release-pipeline (already proposed, awaiting its own
approval) → M7 torrents → m10-vnv-qualification → m10-audit-durability →
m10-pentest → v1.0.0. Rationale for M11-first: the rig context is hot,
change 1 is substantially bug-class, and the amended 1.0 bar
("acquisition-complete") is better served landing intelligence before the
qualification freeze. Alternative if the owner prefers: only change 1
(bug-class) now, changes 2–5 after M10/M7.

## Decomposition — five changes, in dependency order

### Change 1 — `m11-source-import-trust` (bug-class core)

*Findings #9(parser half), #10, #12(minimum), #15, #21 + the 2026-07-27
Saga-TPB verification.*

- **Provenance-authoritative import**: a file arriving from a
  source-matched entitlement imports against that series — only the issue
  needs deriving from the filename. Kills the "Strangelands Issues #8"
  class outright.
- **Ordinal fallback**: parsed `Vol. N` with no issue number resolves to
  issue N when the target series is explicitly known (source match or
  manual-import target). Handles both real trades (Saga Vol. 4 → TPB
  issue 4) and Humble's mislabeled singles (SPAWN Vol. 243 → issue 243)
  because the human-chosen series disambiguates. Parser corpus rows for
  the Humble `Vol.`/`Issues` idioms (additive-only table).
- **Stale-state cleanup**: (a) sibling add-proposals re-resolve to
  match-to-existing after a series-add, and the add action degrades to
  match instead of 400ing on an in-library volume; (b) manual-importing a
  blocked source download clears its queue row and entitlement state.
- **Source-download visibility minimum**: explicit retry action on failed
  entitlement downloads + a health warning when source downloads sit
  failed. (Full Queue/Activity unification stays out — see Non-goals.)
- Spec impact: `imp`/`pp` (matcher requirements ADDED), `sources`
  (MODIFIED download/review-state requirements — complete-scenario
  restatement rule applies), parser corpus rows. Est. 4–6 new ids.
- Surfaces: importer matching, sources review/grab state machine, parser
  corpus, review UI invalidations. Gate: medium tier (no new listener;
  matcher changes get an adversarial mis-match angle). Size: the largest
  of the five in test surface, smallest in novel design.

### Change 2 — `m11-review-experience`

*Findings #7, #8, #9(UI half), #11 + owner ask "jump to the correct
volume id".*

- **ComicVine is the matching universe** (owner direction 2026-07-27):
  proposals and search operate against CV's catalog; the library is a
  shortcut overlay (a candidate already in the library links directly, one
  that isn't is ADDED AND MATCHED in a single action). Library-only
  candidate ranking — the v0 behavior that proposed "Absolute Green
  Arrow" — is retired.
- **Free-text CV search on every row**: always available regardless of
  proposal state; picking a result either links (in library) or
  add-and-matches (not yet added) in one motion. Rides the change-3
  budget lanes if landed, else the existing limiter.
- **Honest proposals, never terminal**: minimum-confidence floor +
  token-overlap gate; "no plausible match" describes only the AUTOMATIC
  verdict and always sits beside the live CV search — no review row is
  ever a dead end.
- **Scale tools**: bulk actions (ignore/match/exclude per bundle/order,
  apply-match-to-group); review rows collapse by franchise/series reusing
  the M3 grouping keys (145 Spawn rows → one expandable group).
- **Classification**: publisher rules + fuller use of Humble item
  metadata to cut RPG contamination; per-bundle exclusion.
- **TPB routing**: items shaped like trades (low ordinal `Vol. N`,
  trade-ish metadata) prefer/offer the collected-edition CV volume in
  proposals — the owner's "shouldn't it jump to the correct volume id".
- Spec impact: `sources` (review requirements ADDED/MODIFIED), `ui`.
  Est. 4–6 new ids. Gate: medium. Depends on change 1 (stale-state fixes
  underneath the new picker).

### Change 3 — `m11-cv-budget`

*Findings #13, #14, #20 + the meter/early-warning riders.*

- **Calibration**: read ComicVine's own per-path usage counters and
  reconcile the local sliding-window shadow count against them (the
  observed 150-local vs 136-actual gap).
- **Priority lanes**: batch consumers (refresh, credits, covers, sync)
  capped at a share of each path budget and made to yield; interactive
  requests get a protected reserve. Explicit non-goal recorded in spec:
  no multi-key support, ever (ToS-spirit position).
- **Sync frugality**: the nightly source-sync stops re-searching CV for
  known-unmatched entitlements (negative-result cache; search only new
  arrivals) — the verified nightly 23:00 budget exhaustion dies.
- **Visibility**: approaching-limit health warning (before exhaustion,
  which already warns) + a budget meter surfaced where spend happens.
- Spec impact: `meta` (MODIFIED FRG-META-016 — complete restatement — +
  ADDED lanes/calibration), `sources` (sync behavior), `ui` (meter),
  `api` (budget surface). Est. 4–5 new ids. Gate: medium.

### Change 4 — `m11-acquisition-responsiveness`

*Findings #1, #2, #3, #5.*

- **Search-on-add mini-sweep**: a newly added monitored series (or a
  first-configured indexer) triggers a bounded immediate search instead
  of waiting for the 6-hour tick; "next automatic search at …" surfaced.
- **Interactive search stops waiting for the slowest indexer**:
  per-indexer time budget with partial results and an honest "indexer X
  timed out" outcome — retires the rig's listener-timeout band-aid.
- **Path-visibility health**: a completed download whose file the
  importer cannot see for N cycles degrades health with an actionable
  message (the Die Loaded silent-stall, never again).
- **Priority UI**: the numeric priority field on indexer and
  download-client forms (API already supports it).
- Spec impact: `srch` (ADDED + MODIFIED search-flow requirements), `dl`
  (visibility health), `ui`, `idx`. Est. 4–5 new ids. Gate: medium
  (timeout/partial-results logic gets a concurrency-focused angle).

### Change 5 — `m11-discovery-surface`

*Findings #17 + the talkhard-payload riders; the only security-touching
change.*

- **Add from anywhere**: every unmatched Calendar entry offers the add
  affordance (prefilled add flow) — FRG-PULL-008's #1-only gate widens;
  the "New this week" section becomes badges/filter rather than a
  confusing separate stack.
- **Pull covers**: ingest the talkhard payload's cover URLs; serve them
  through the existing cover proxy, whose host allowlist grows by the
  LOCG S3 host — **new egress target ⇒ security-touching**: full-tier
  gate, threat-model delta, abuse scenarios, per FRG-PROC-006.
- **Pull enrichment**: store creators/description/UPC from the payload
  the ingest currently drops; render where the Calendar/entry UI can use
  them. Budget-free (no CV involvement).
- Spec impact: `pull` (MODIFIED FRG-PULL-008 — complete restatement — +
  ADDED ingest/enrichment), `meta` (MODIFIED FRG-META-021 allowlist),
  `ui`. Est. 3–5 new ids. Gate: **full fleet + Codex** (allowlist growth).

## Non-goals (recorded now so scope can't creep)

- Read-only sources (finding #4) — real feature, own future change.
- Trade-file handling beyond the ordinal fallback (format-preference
  direction owns grab/keep/serve semantics).
- Radarr-style custom-format scoring.
- Pack handling (M7 torrents owns 1→N).
- Full Queue/Activity unification of source downloads (change 1 ships the
  retry + health minimum only).
- Any multi-key ComicVine mechanism.

## Estimated shape

Five releases (v0.9.24-ish onward), each change independently gated and
released; change 1 is the largest test surface, change 5 the only
full-fleet gate. Registry ids: ~20–27 across imp/pp/sources/meta/srch/
dl/ui/idx/pull — allocated per change at proposal time. Manual impact:
changes 2, 4, 5 touch user-facing docs; declared per proposal.

## Approval

_Pending owner review of THIS document (FRG-PROC-009). Nothing in this
milestone is approved yet — including its sequencing and any standing
grant; the owner explicitly reset premature approval records on
2026-07-27. Decisions requested: (1) the five-change decomposition, (2)
M11-before-M10-resumption sequencing, (3) whether M11 runs under a
standing grant or gate-by-gate._
