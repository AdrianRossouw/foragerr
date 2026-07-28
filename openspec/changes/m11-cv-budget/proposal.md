# m11-cv-budget — spend the ComicVine budget like it's scarce

## Why

The live rig's nightly source sync verifiably exhausted a ComicVine path
budget at 23:00 (finding #20), the local shadow-count refused requests
while ComicVine's own dashboard showed real headroom (finding #13:
sliding 150/150 locally vs 136 used on a fixed window), background jobs
and an operator's interactive search compete for one undifferentiated
budget (finding #14), and the only budget visibility is a warning that
fires after exhaustion. One key, spent carelessly, starves the surfaces
the operator is actually looking at.

**Scope adjustment, recorded up front**: the pre-design imagined
calibrating by *reading ComicVine's own usage counters*. Verified
empirically at proposal time (authenticated probe, 2026-07-28): CV's API
responses carry **no** rate/usage headers and no usage fields — only CDN
cache headers and pagination. The counters the owner saw are the human
dashboard. Calibration therefore becomes: honest observability (a real
meter from the numbers the gate already computes), an approaching-limit
warning before the wall, and documented window semantics — not
counter-reading, which does not exist to read.

## What Changes

- **Priority lanes within one key** (new `FRG-META-022`): every CV
  acquisition declares a lane — `batch` (refresh, credits, covers,
  enrich, backfills) or `interactive` (lookup/suggest, add, row search,
  restore, library-import grouping, connection test). Batch admission is
  capped at a configurable share of each path budget (default 70%) so an
  interactive reserve always exists; interactive requests may consume
  the full budget. Never multi-key — recorded as a spec non-goal with
  the ToS-position rationale.
- **Approaching-limit health warning** (MODIFIED `FRG-META-016`): a
  path bucket crossing the existing 80% warning fraction surfaces as a
  distinct degraded-class health state *before* exhaustion (today the
  80% data is computed and then ignored until 100%).
- **Budget meter** (new `FRG-API-025`, `FRG-UI-040`): the health
  component carries structured per-path numbers (used/ceiling/lane
  split/resume seconds — already computed server-side, never exposed);
  Settings → General renders the meter beside the ComicVine key, and
  the Sources review screen shows a compact meter while spend is
  happening there. The lookup-search outcome note stops masking the
  backend's budget-resume message behind a generic failure string.
- **Enrichment frugality** (new `FRG-SRC-013`): the nightly enrich run
  orders its pending set by least-recently-attempted (new
  `proposal_attempted_at` stamp, migration) so a failing or deferred
  head can no longer starve the tail night after night; CV-error rows
  retry with attempt spacing instead of every night forever.
- **Budget-aware bulk recompute** (rider on `FRG-SRC-013`): an operator
  action recomputes stale (pre-v0.11, library-ranked) proposals in
  batches through the batch lane, resumable across budget windows —
  closing the v0.11.0 upgrade-note gap. Marker rows recompute when the
  ComicVine key configuration changes (the no-key → keyed transition).
- **Docstring truth**: the rate-gate module claim that "cover fetches"
  all pass the gate is corrected — the candidate-cover proxy fetches
  media-CDN bytes outside the API budget by design (FRG-META-021's
  host), and the covers *cache* path stays budgeted.

## Capabilities

### New Capabilities

None — extensions of existing areas.

### Modified Capabilities

- `meta`: ADDED FRG-META-022 (priority lanes; multi-key non-goal),
  MODIFIED FRG-META-016 (approaching-limit health state; structured
  budget observability; window-semantics note incl. the verified
  no-counters result; complete restatement).
- `sources`: ADDED FRG-SRC-013 (enrichment attempt-ordering + spaced
  retry + stale-proposal bulk recompute + marker revisit on key
  change).
- `api`: ADDED FRG-API-025 (structured budget state on the system
  health surface).
- `ui`: ADDED FRG-UI-040 (budget meter in Settings and the review
  screen; resume-time fidelity in lookup outcome notes).

## Impact

- Backend: metadata/ratelimit.py (lane dimension on the one gate),
  metadata/comicvine.py + covers.py (lane threading at the client
  seam), sources/enrich.py + repo.py + commands.py (+ migration 0027
  proposal_attempted_at; the recompute action lives beside the
  enrichment machinery it reuses),
  health/service.py, api/system.py + api/sources.py.
- Frontend: Settings General meter, Sources compact meter, AddSeries
  lookup outcome-note fix.
- DB: migration 0027 (nullable timestamp; no data rewrite).
- No dependency changes (SOUP untouched). No new attack surface: the
  meter exposes counts on the existing authenticated health surface;
  the recompute action rides existing authenticated source endpoints;
  no new listener/parser/egress. Rationale recorded per FRG-PROC-006.
- Manual impact (FRG-PROC-011): admin configuration page (lanes +
  budget settings), user sources page (meter + recompute), metadata
  page if present.

## Non-goals

- Multi-key ComicVine anything (spec-recorded, ToS-spirit position).
- Reading CV usage counters (verified non-existent on the API).
- Raising the default 150 soft ceiling (observability first; the
  operator can tune with the meter in view; revisit with evidence).
- Cover-proxy budgeting (media CDN, outside the API budget by design).
- Cross-restart budget persistence (accepted in FRG-META-016 as-is).

## Approval

Proposed under the M11 standing grant (owner approval 2026-07-27,
recorded in the m11-import-intelligence pre-design's Approval section,
commit 562b16f). The counters-to-observability scope adjustment above is
this proposal's one deviation from the pre-design's wording, driven by
the verified probe; it is flagged for the owner's attention at the next
touchpoint rather than blocking under the grant. No intent-presuming
defaults: lanes change *scheduling*, never what is fetched; the bulk
recompute is operator-triggered; nothing new is acquired automatically.
