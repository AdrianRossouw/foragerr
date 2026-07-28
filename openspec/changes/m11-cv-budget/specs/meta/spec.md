# meta — delta for m11-cv-budget

## ADDED Requirements

### Requirement: FRG-META-022 — Batch and interactive priority lanes within one key

The system SHALL classify every ComicVine acquisition into one of two
lanes on the single shared gate — `batch` (scheduled and background
work: refreshes, credit backfills, cover caching, source enrichment,
bulk recompute) or `interactive` (an operator is waiting: lookup and
suggest, series add, per-row review search, restore recompute,
library-import grouping, connection tests) — with `batch` as the
default for an unclassified caller. Batch admissions SHALL be capped at
a configurable share of each path budget (default 70%, clamped between
30% and 95%) so an interactive reserve always exists; interactive
admissions may consume the full path budget. Lane accounting SHALL
share the one process-global gate and the FRG-META-016 window — a
third dimension beside velocity (FRG-META-003) and the path budget,
never a second gate. The system SHALL NOT support multiple ComicVine
API keys in one deployment — splitting one operator's traffic across
keys to multiply the documented per-key limit is against the API
terms' spirit and the project's polite-citizen posture; this is a
permanent non-goal, not a deferral.

#### Scenario: Batch pauses first, interactive keeps a reserve

- **WHEN** batch consumers have used the batch share of a path budget
  and both a batch and an interactive request arrive on that path
- **THEN** the batch request is refused with the typed budget error
  (naming the lane and resume time) while the interactive request is
  admitted from the reserve

#### Scenario: Interactive exhaustion is still honest

- **WHEN** interactive traffic alone consumes a path's full budget
- **THEN** further requests on that path are refused with the typed
  error exactly as FRG-META-016 specifies — the reserve is a floor for
  interactivity, never an extra allowance beyond the path ceiling

#### Scenario: Unclassified callers cannot eat the reserve

- **WHEN** a caller acquires without declaring a lane
- **THEN** it is accounted as batch — a new background job added
  without lane awareness degrades itself, never the operator's
  interactive surfaces

#### Scenario: One key only

- **WHEN** deployment configuration is inspected for ComicVine
  credentials
- **THEN** exactly one API key is configurable; no mechanism exists to
  distribute traffic across multiple keys

## MODIFIED Requirements

### Requirement: FRG-META-016 — Per-path hourly request budget with defer-and-resume

The system SHALL account ComicVine requests per resource path (the first,
normalized URL path segment — the granularity ComicVine's own 200/hour limit
uses) over a rolling one-hour window, and SHALL refuse to issue a request on a
path whose soft budget (default 150/hour, configurable with a floor of 10 and
clamped to at most 200) is exhausted, raising a typed budget error that
carries the path bucket and the seconds until capacity returns instead of
sending the request. A budget refusal is a local decision: it SHALL NOT flip
the rate-limit degraded/back-off state, and it SHALL NOT block the caller
until capacity returns. Budget state SHALL be observable in the ComicVine
health payload (per-path usage for paths near or at their ceiling, plus an
exhausted flag), and a path bucket that crosses the warning fraction of its
ceiling SHALL surface as a distinct approaching-limit health state BEFORE
exhaustion — independent of the 429 back-off and auth-failure dimensions —
whose message names the bucket, the usage, and which lane (FRG-META-022) is
paused first. Every deferral SHALL be logged — never silent. Work
interrupted by a budget refusal SHALL resume without operator action:
bounded backfills (issue-credit fetches) stop cleanly for the run and later
runs pick up the unfinished remainder via their existing progress stamps;
command-based fetches record the failure and retry via their existing
staleness paths; interactive lookups surface the typed error through the
existing lookup-error surfacing with the resume time. The accounting is
local by design: ComicVine's API responses expose no usage counters
(verified 2026-07-28 — no rate headers, no usage fields), so the local
window is authoritative and its semantics (rolling, restart-forgetting)
are documented rather than reconciled against an unreadable remote
counter.

- **Milestone**: M6
- **Source**: ComicVine rate-limit documentation + owner's live per-path
  usage data (2026-07-12): 200/hour per resource path per key; `/issue` at
  75/hour under light use via the credits detail fetches. Gap analysis in
  the cv-budget-caching proposal. Counter-reading infeasibility verified by
  authenticated probe at the m11-cv-budget proposal (2026-07-28).
- **Notes**: Complements, not replaces, the velocity gate (FRG-META-003) —
  spacing prevents bursts; the budget prevents hour-scale exhaustion the
  spacing math permits (~1800/hour at the 2 s default). Restart forgets the
  window (accepted: server-side 420/429 back-off remains the second line of
  defense). Single-process accounting by design — same posture as the
  process-global gate. The gate's budgeted surface is the ComicVine API and
  the covers cache; the candidate-cover proxy fetches media-CDN bytes,
  which are outside the API budget (FRG-META-021's egress host), by design.

#### Scenario: Exhausted path refuses locally without touching other paths

- **WHEN** the configured hourly budget for one path bucket is consumed and a
  further request is attempted on that path while another path has remaining
  budget
- **THEN** the same-path request raises the typed budget error (carrying the
  bucket and seconds-until-resume) without any wire request and without
  flipping the degraded flag, and the other-path request proceeds normally.

#### Scenario: Credit backfill defers cleanly and resumes on a later run

- **WHEN** the issue-credit detail phase of a series refresh hits the budget
  refusal partway through its bounded target list
- **THEN** the refresh completes successfully with the credits fetched so
  far, the remaining issues stay unstamped, the deferral is logged, and a
  subsequent refresh run (with budget available) fetches the remainder.

#### Scenario: Budget state is visible in health

- **WHEN** a path bucket crosses its warning threshold and then exhausts
- **THEN** the ComicVine health payload reports that bucket's usage, ceiling,
  and seconds-until-resume, and an exhausted indicator, and the payload
  returns to its compact form once the window rolls over.

#### Scenario: Approaching the ceiling warns before the wall

- **WHEN** a path bucket's usage crosses the warning fraction of its
  ceiling while requests are still being admitted
- **THEN** application health shows a distinct approaching-limit warning
  naming the bucket, its usage against its ceiling, and the lane paused
  first — before any interactive request has been refused (the batch
  lane may already be pausing at its share, and the message says so
  when it is) — and the warning clears when the window rolls the bucket
  back under the fraction.

#### Scenario: A paused batch lane alone is not a health warning

- **WHEN** batch consumers have reached their share of a path budget
  while total usage remains below the warning fraction
- **THEN** application health stays ok (the pause is the designed
  steady state of a heavy background run, not an anomaly), while the
  budget detail still carries the bucket so the meter can show the
  paused lane

#### Scenario: Window rolls — capacity returns without operator action

- **WHEN** requests admitted more than one hour ago age out of the rolling
  window
- **THEN** new requests on the previously exhausted path are admitted again
  automatically.

#### Scenario: Ceiling configuration is clamped to ComicVine's documented limit

- **WHEN** the hourly budget setting is configured above 200 or below the
  floor
- **THEN** the effective ceiling is clamped into the documented bounds with a
  warning rather than accepting an unsafe value.
