# m11-source-import-trust — design

## Context

Research mapped the exact seams (all citations verified 2026-07-28):

- `importer/pipeline.py:451-520` `_reconcile_base()` resolves in order:
  (1) `[__issueid__]`/`[cvid-N]` tag, (2) grab-history short-circuit —
  which requires **both** `grab_series_id` AND `grab_issue_id`
  (`pipeline.py:494-496`), (3) filename parser heuristic, which for an
  unscoped candidate does an **exact** `matching_key` lookup and bails
  immediately when `evidence.issue is None` (`pipeline.py:498-500`).
- Store grabs always write `GrabHistoryRow(series_id=matched,
  issue_id=None)` (`sources/grab.py:293-304`), so step 2 never fires for
  them and step 3 never consults `grab_series_id`. That is finding #15.
- The parser keeps `volume_ordinal` strictly distinct from `issue`
  (`parser/result.py`), so "SPAWN Vol. 243" → `issue=None,
  volume_ordinal=243`. "Issue"/"Issues" is in no vocab list and leaks
  into `series_name` ("Strangelands Issues"). Corpus:
  `tests/parser/corpus.py`, 81 rows, count-asserted, additive-only
  (FRG-IMP-021).
- `sources/review.py:add_entitlement` catches every `add_series`
  exception as a 400 (`review.py:190-193`); the "already in the library"
  guard is `library/flows/add.py:145-151`. Nothing re-resolves sibling
  proposals after an add — a backend gap, not a cache gap (the frontend
  refetches correctly on mutation).
- `downloads/manual_import.py:execute_manual_import` calls
  `import_candidate` per file but never `_apply_state` (queue row stays
  terminal-stale, no WS queue event) and never `apply_source_import`
  (entitlement never advances; owned-via-edition reconciliation skipped —
  brushes FRG-SRC-007).
- No retry affordance exists anywhere (spec FRG-SRC-006 promises one);
  the only re-queue path is re-match/re-add (`review.py:60`
  `_QUEUEABLE_STATES = (None, "failed")`). `health/service.py`
  `_sources_component` (508-556) never inspects `download_state`.

## Goals / Non-Goals

**Goals:** trust operator-established provenance end-to-end; make
`Vol. N` files land when the series is known; keep review proposals
truthful after mutations; leave no stale queue/entitlement state behind a
manual import; make source-download failure visible and retryable.

**Non-Goals:** unscoped-matching semantics changes, Queue/Activity
unification, review-picker/bulk UX (change 2), budget behavior
(change 3), remote path mappings (change 4).

## Decisions

**D1a — Gate amendments (2026-07-28, from the adversarial + state-machine
review angles; findings verified empirically before adoption).** Four
hardenings to D1/D2 as originally written: (i) provenance authority is
**store-gated** — a series-only grab hint from a non-store grab (an
indexer force-grab whose release mapped a series but no issue) keeps
pre-change behavior; (ii) store provenance resolves from the
entitlement's **current** match at import time, not the grab-time
snapshot — a re-match between grab and import is honored and a
dangling/deleted series withdraws authority; (iii) the ordinal fallback
gains three guards (trade-booktype refusal against non-collected series,
never-replace-an-existing-file, operator-made-match-only — auto-sync
matches block for review), closing the verified
trade-deletes-single blocker and the no-human auto-route (measured:
bare `Vol. N` store titles clear the 0.85 auto-match bar, e.g. "The
Unbeatable Squirrel Girl Vol. 2" at 0.889); (iv) a retry from a failed
*import* clears the stale terminal tracked row before re-queueing so the
re-grab hands off fresh instead of dedup-wedging at import_pending. The
operator-made-match discriminator is a new `matched_via` column on
source entitlements (migration), stamped by the match/add actions vs
auto-sync.

**D1 — Split the grab short-circuit, keep tag precedence.**
`_reconcile_base` step 2 becomes two cases: (a) both ids present →
unchanged; (b) `grab_series_id` present, `grab_issue_id` None → the
series is fixed; derive the issue within it: try
`_match_issue_in_series(evidence.issue)`, then the D2 ordinal fallback.
If neither lands, return `(series_id, None, …)` so the rejection reads
"matched series … but no issue could be derived" rather than "could not
match this file to a known series and issue" — `MappedToIssueSpec`
still blocks it (manual import remains the escape hatch), but the reason
is honest and series-scoped. Control NEVER falls to step 3's unscoped
lookup when a provenance series exists — falling through would let a
parseable-but-wrong filename override the operator's explicit match,
inverting FRG-PP-004's confidence order (grab record outranks filename).
Alternative considered: relaxing step 2's `and` to accept the hint pair
as-is — rejected, it would import to issue None or demand schema
changes; the series-scoped derive keeps `issue_files` invariants intact.

**D2 — Ordinal fallback lives in the pipeline, not the parser.**
When a series is explicitly known (D1's provenance case; also the
series-scoped rescan branch) and `evidence.issue is None` but
`evidence.volume_ordinal` is not, build a synthetic
`Issue(value=Fraction(volume_ordinal))` and run it through the same
`matching.match_issue_id`/`issue_equal` index. Safety comes from the
index: the fallback only lands when issue N actually exists in the
operator-chosen series (SPAWN #243 exists → lands; a stray "Vol. 9" in
a 5-issue series → blocked). The parser's `volume_ordinal`/`issue`
separation (FRG-IMP-012) is untouched — teaching the parser
"Vol-means-issue" globally would corrupt every legitimate trade parse.
The fallback is attempted after a real-issue miss too (evidence.issue
present but not in index is still a miss → blocked; we do NOT let the
ordinal override a present-but-unmatched issue — a present issue number
is stronger evidence than a volume token; restated as a spec scenario).

**D3 — Filler stripping is anchored, narrow, and corpus-pinned.**
Tokenizer/assembly change: a bare `issue`/`issues` WORD token is
consumed (excluded from `series_name`) only when immediately followed by
an issue anchor (`#`) or by the token that becomes the selected issue
number. No vocab-list growth beyond this rule; "The Death Issue" or a
series title containing "Issue" mid-phrase is unaffected because the
following token is not its issue evidence. New corpus rows (appended,
count assert bumped): `SPAWN Vol. 243` (pins issue=None,
vol=243 — the pipeline, not the parser, resolves it), `Spawn #211`,
`SPAWN Issue # 279` (series "SPAWN"), `Strangelands Issues #8` (series
"Strangelands"), `Something is Killing the Children Vol. 8`.

**D4 — Add degrades to match; siblings re-resolve; server-side.**
`add_entitlement`: before calling `add_series`, look up
`SeriesRow.cv_volume_id == cvid`; if present, delegate to
`match_entitlement` (idempotent, still queues the grab per existing
`_QUEUEABLE_STATES`). On a *successful* add, in the same transaction,
sweep sibling `source_entitlements` rows (`review_status="new"`) whose
`proposed_match_json` names the same `cv_volume_id` and rewrite their
proposals to `kind:"library"` match proposals targeting the new series
(preserving candidates list, marking `auto: false`). Server-side because
the frontend already refetches on mutation — fixing the rows fixes every
client. Alternative (UI-side re-mapping) rejected: leaves the API lying
and re-breaks on the next client. The catch-all
`except Exception → 400` in `add_entitlement` narrows so real
add-series failures still 400 but the in-library case never reaches it.

**D5 — Manual import applies the same terminal path as the drain.**
`execute_manual_import` gains the drain's ending: compute the aggregate
terminal state for the download's tracked row (imported if ≥1 file
imported and none blocked/failed remain unresolved — reuse the drain's
existing aggregation helper rather than a second policy), apply it via
`_apply_state` (emitting the queue WS event), and call
`apply_source_import` in the same write transaction when `download_id`
belongs to a source (`humble:` prefix — the existing
`import_hook` resolution). Files without a `download_id` (arbitrary
folder imports) are unaffected. This is deliberately the *same* code
path as `ProcessImportsCommand`'s ending, extracted if needed, so
FRG-SRC-007's owned-via-edition reconciliation runs exactly once and
identically in both flows.

**D6 — Retry is a first-class action; health watches failed downloads.**
`POST /sources/entitlements/{id}/retry-download`: valid only when
`download_state == "failed"` (409 otherwise), clears `download_error`,
re-queues via the existing `_queue_grab` seam. UI: a Retry button on
`download_state === 'failed'` rows next to the existing failure note.
Health: `_sources_component` (or a sibling producer registered beside
it) emits one degraded `ComponentHealth` per source with N failed
entitlement downloads (aggregated per source, not per row — 1,318-row
collections must not spam 100 health lines), message carries the count
and oldest failure, remediation points at the Sources screen retry.
Threshold: any failed row degrades (no N-cycle debounce here — failure
is already terminal, unlike change 4's visibility polling).

## Risks / Trade-offs

- [Provenance overrides a correct filename that names another series
  (mis-matched entitlement)] → the operator's match is the contract;
  re-match + ignore flows exist, the rejection message names the series
  it targeted, and manual import overrides file-by-file. Adversarial
  gate angle probes this.
- [Ordinal fallback mis-files a true trade into a singles series when
  issue N exists] → only fires with issue evidence absent AND an
  explicit series; the operator chose the series for that entitlement;
  a wrong landing is recoverable (unmonitor/delete + manual import) and
  the alternative (today) is a guaranteed block.
- [Sibling sweep rewrites a proposal the operator was mid-decision on] →
  rewrite only touches `review_status="new"` rows and converts a
  now-impossible action into the equivalent possible one; the row stays
  in review.
- [Manual-import terminal aggregation diverges from drain policy] →
  mitigated by reusing/extracting the drain's aggregation, plus a test
  asserting both paths produce identical state for the same fixture.
- [Filler stripping changes `series_name` for existing libraries] →
  parse output changes only for names with the anchored filler pattern;
  corpus pins the new expectations; rescan matching uses the subset
  matcher, for which a *shorter* stripped key can only match more
  correctly (the filler word was the thing defeating it).

## Migration Plan

One additive migration (0025): nullable `matched_via` on
source_entitlements ('operator' | 'auto'; NULL for legacy rows, which
withhold the ordinal fallback with an honest "predates match tracking"
reason — one operator re-match restores it). All other behavior changes
are import-time and review-time only; existing library rows are
untouched. Rollback = revert the release tag (the column is inert to
older code).

## Deferred follow-ups (recorded at the simplify pass, 2026-07-28)

The pre-merge simplify review judged these real but not worth churning a
thrice-reviewed green branch; change 2 (or a dedicated cleanup) should
pick them up, in this order:

1. **Pipeline resolution contract**: `reconcile()` returns a result
   object (series, issue, ordinal refusal, comicinfo conflict) instead
   of a 2-tuple plus `evidence.provenance` side-channel — removes the
   `PROV_ORDINAL_REFUSED` retraction `pop` that falsifies the decision
   trace; `_reconcile_base` returns a `BaseResolution` with an explicit
   `series_is_authoritative` flag instead of the `_BASE_GRAB_SERIES`
   magic string; the series-only manual override joins
   `_derive_issue_in_series` (gaining the ordinal fallback + honest
   reason). Contained to pipeline.py; no test calls `reconcile` directly.
2. **`matched_via` fail-closed threading** (safety-ranked first): make it
   a required keyword on the internal chain and assert
   `MATCHED_VIA_OPERATOR` explicitly at each API endpoint — today the
   privileged value is the default, so a forgotten forwarding hop would
   silently unlock the FRG-PP-022 guard-3 gate.
3. **Sibling sweep source-scoping**: add the acting entitlement's
   `source_id` predicate so the sweep rides the
   (`source_id`, `review_status`) index instead of scanning all sources'
   review rows per add (cross-source siblings self-heal via the degrade
   path regardless).
4. **Name the withdrawal gate** (`withdraw_if_no_longer_accepted`
   collapsing its three call sites), promote `_withdraw_import` to a
   public name, and add an `evaluate_candidate` helper for the
   thrice-repeated `aggregate → build_evaluation → decide` triple.
5. **`SeriesWithoutIssueSpec`**: split the series-named mapping failure
   out of `MappedToIssueSpec` so one spec name means one reason (no spec
   delta required — requirements describe reason content, not classes).

## Open Questions

None blocking — the rig reproduces findings #10/#15 verbatim for
verification (Strangelands entitlements + SPAWN corpus live there).
