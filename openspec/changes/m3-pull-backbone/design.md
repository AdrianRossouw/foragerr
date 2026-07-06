# Design — m3-pull-backbone

## Context

Grounding (research-verified against the current tree at v0.2.8):

- **Scheduler + commands.** `commands/scheduler.py::IntervalScheduler.register_task`
  registers a recurring task that enqueues a named command at
  `last_run + interval` (never immediately-on-start), clamping the interval to a
  documented minimum; built-ins are listed in `commands/__init__.py`
  `BUILTIN_SCHEDULED_TASKS` (currently just `housekeeping`). Force-run is
  `scheduler.force_run` behind `POST /api/v1/system/task/{name}` (FRG-API-014 /
  FRG-SCHED-007) — the same surface "back up now" uses. Command dedup is
  FRG-SCHED-003; job history is FRG-SCHED-008; status push to the UI is
  FRG-SCHED-010 over the WS bus.
- **`refresh-series` already exists.** `library/flows/_common.py::RefreshSeriesCommand`
  (`name = "refresh-series"`) is the metadata-refresh command enqueued by the add
  flow (`library/flows/add.py`, `triggered_by="add-series"`); it reconciles issues
  (FRG-META-008) and honours the series' monitor-new-items policy (FRG-SER-007).
  The pull refresh trigger enqueues *this exact command*, deduplicated on the
  queue — it does not invent a pull-specific refresh.
- **Matching machinery exists.** `library/matching.py` provides
  `series_title_matches`, `_norm_name` (normalized name), `issue_equal`,
  `build_issue_index`, `match_issue_id`. The pull matcher is a thin adapter over
  these plus the guarded date-window / sequence-delta checks the baseline
  requires — not a second identity implementation.
- **Hardened egress + untrusted content.** The `security` package owns the egress
  factory with `external` vs `local_service` profiles (FRG-SEC-001: per-hop
  scheme/DNS validation refusing loopback/private/link-local, mandatory timeouts,
  disabled auto-redirects). The pull source is fetched over the **`external`**
  profile against a config-supplied URL. Untrusted-content handling is FRG-NFR-012.
- **Health + config.** Component health is FRG-NFR-011 aggregated by FRG-API-014
  (`/api/v1/health`, items `{source, type, message, remediationHint}`); a degraded
  pull source is one such item. Config is `config.py` (pydantic BaseSettings, env +
  file, validated at startup, FRG-NFR-009); new pull keys live there and migrate
  via FRG-DEP-004.
- **Issue/queue state.** Derived wanted state is FRG-SER-004; the queue/tracked-
  download projection is FRG-DL-008 / FRG-API-007. The weekly projection reads
  these — it does not maintain its own copy of issue state.
- **DB discipline.** New tables ride FRG-DB-002 (versioned migrations, alembic
  under `db/alembic`) + FRG-DB-008 (typed, sentinel-free schema); no DB
  requirement changes.

Risk register already anticipates this integration: **RISK-039** (external
weekly-pull JSON source) and the open **pull-source arm of RISK-025** (SSRF via a
config-supplied source host). No new risk id is expected.

## Goals / Non-Goals

**Goals:** a library-primary weekly projection with derived state; a configurable,
hardened, health-reporting external pull-source fetch; idempotent per-week
storage; a guarded matcher reusing library identity; a refresh trigger that rides
`refresh-series`; a scheduled + manual refresh on the SCHED backbone; one minimal
read endpoint for change 2.

**Non-Goals:** the pull screen and per-entry actions (change 2, FRG-UI-018 /
FRG-PULL-007..009); auto-add / auto-want writes from the pull side; trade typing
(M3 ch5); a fallback/second source; weekly folders; one-off unwatched downloads.

## Decisions

### 1. Backbone / experience split (and why it composes)

**Backbone (this change) = FRG-PULL-001..006 + FRG-API-019** — the data model,
fetch, storage, matching, refresh-trigger, schedule, and one read endpoint.
**Experience (change 2) = FRG-UI-018 + FRG-PULL-007..009** — the screen, per-entry
want/skip/search, new-series surfacing, and future-week forward navigation.

The split is along a clean seam because the backbone's output — a per-week list of
entries, each either *linked to a library issue* (with that issue's derived state)
or *unmatched* / *new-series* — is exactly what the screen renders, and every
screen action is a delegation to a canonical operation that already exists
(issue monitored-toggle FRG-API-004, issue search FRG-SRCH-008/014, add flow
FRG-SER-005) rather than a new pull-side mutation. This is enforced by the D4
invariant (decision 4): **pull entries never own status**. Consequences:

- FRG-PULL-001 (projection) is verifiable in the backbone via the API + service
  tests; change 2 re-uses it for rendering without re-verifying it.
- FRG-API-019 accepts an arbitrary `week`, so prev/current/next navigation
  (part of FRG-PULL-001's baseline and FRG-PULL-009's forward nav) is three calls
  from the screen — the backbone needs no navigation logic.
- FRG-PULL-007/008/009 add no storage: want/skip/search project onto issue+queue
  state; new-series surfacing reads unmatched `#1/#0` entries the backbone already
  stores; future releases are just entries stored for a future week.

Rejected alternative: one big `m3-pull` change. It would couple a new outbound
integration and the correctness-critical matcher to React work in a single
worktree, defeating FRG-PROC-008 parallelism and making the gate review harder.

### 2. Pull-source choice and trust posture

**Default source: the walksoftly / League-of-Comic-Geeks-derived JSON API**
named in the FRG-PULL-002 baseline (`newcomics.php?week=&year=`), **configurable**
via `pull_source_url` because the service is unofficial and has moved before. Only
this one source is supported — the legacy PreviewsWorld scrape and flat-file paths
Mylar carried are dead code and are **not** reimplemented.

**Trust posture (the load-bearing part):**

- The fetch runs over the `security` **`external`** egress profile (FRG-SEC-001),
  so a source URL pointed at loopback/private/link-local is refused per-hop —
  this closes the **pull-source arm of RISK-025** (SSRF). The source URL is
  operator-configured, not attacker-supplied, but the profile is applied anyway
  (defence in depth; the operator can still fat-finger an internal host).
- Mandatory connect/read timeouts (FRG-NFR-006); no auto-redirect.
- The response body is **untrusted JSON** (FRG-NFR-012): parsed with the stdlib
  under a byte cap, each field validated/coerced to the typed entry model,
  source-supplied ComicVine IDs recorded but **not trusted as authority** — they
  are *candidates* the matcher (decision 5) still guards. A malformed or hostile
  payload degrades to "fetch failed / stale data", never a crash and never a
  partially-written week (decision 3's replace-on-refresh is transactional).
- Documented source error codes are mapped explicitly: **619** (bad date) → skip
  that week with a logged warning; **522** (backend down) and **666**
  (client-update-required) → treat as source outage. **On any outage the previous
  fetch's stored week is left intact** and the pull source is marked **degraded**
  in health (FRG-NFR-011 / FRG-API-014) — the weekly view still renders from local
  metadata (FRG-PULL-001). This realises **RISK-039**'s mitigation.
- The source is **optional enrichment**: with `pull_enabled=false` or no
  `pull_source_url`, no fetch happens and FRG-PULL-001 still works.

### 3. Per-week storage shape (idempotent re-fetch)

A single new table **`pull_entries`**, typed (FRG-DB-008), roughly:

```
pull_entries(
  id            INTEGER PK,
  week          TEXT   NOT NULL,   -- ISO year-week key, e.g. "2026-W27"
  entry_key     TEXT   NOT NULL,   -- stable per-(week) identity (see below)
  publisher     TEXT,
  series_name   TEXT   NOT NULL,
  issue_number  TEXT   NOT NULL,   -- raw source token; normalized on match
  cv_series_id  INTEGER,           -- source-supplied, nullable, candidate only
  cv_issue_id   INTEGER,           -- source-supplied, nullable, candidate only
  release_date  DATE   NOT NULL,
  matched_issue_id INTEGER NULL REFERENCES issues(id),   -- the LINK (D4)
  match_type    TEXT   NOT NULL,   -- 'id' | 'name_seq' | 'unmatched' | 'new_series'
  fetched_at    TIMESTAMP NOT NULL,
  UNIQUE(week, entry_key)
)
```

**Idempotency = per-week replace-on-refresh** inside one transaction (FRG-DB-007):
a refresh of week *W* deletes all `pull_entries` for *W* and re-inserts the fetched
set, so repeated fetches of the same week yield identical row counts + content.
`entry_key` is derived deterministically from the source entry (prefer
`cv_issue_id`; else a normalized `(series_name, issue_number, publisher)` tuple) so
the same source row maps to the same logical entry across refreshes. **The entry
carries only a `matched_issue_id` link and a `match_type` — never a
wanted/downloaded status** (D4): Mylar's `weekly.STATUS` and its separate
`upcoming` / `futureupcoming` tables collapse into this one store plus the
metadata-derived projection. Matching is stored on the entry (decisions 4–5) so
the read endpoint is a cheap join, not a re-match per request.

### 4. Match confidence model (D4 — entries link, never own status)

`match_type` is the confidence record:

- **`id`** — high confidence: source `cv_issue_id` (or `cv_series_id` + issue
  number) resolves to a library issue via the existing CV-id identity. Retains
  Mylar's **book-type guard** on id matches (an id match to a wrong book-type is
  rejected).
- **`name_seq`** — guarded medium confidence, accepted only if **all** hold
  (Mylar's hard-won guards, kept as explicit acceptance fixtures):
  normalized series name equals a watched series' name or alias
  (`library/matching.py` normalization), **AND** issue number is a plausible
  next-in-sequence (`0 ≤ delta < 3` vs the series' latest known issue),
  **AND** release date is within the pull week **±2 days**.
- **`unmatched`** — known-series-collision-rejected or unknown series: stored as
  unmatched, **never guessed** into a link. A wrong-volume name collision is
  exactly what the date-window + sequence guards reject.
- **`new_series`** — an unmatched entry whose issue number is `#1`/`#0` and whose
  series is not in the library: tagged for change 2's new-series surfacing
  (FRG-PULL-008). The backbone only *tags*; it does not add.

Annual matching flows through typed annual issues (SER/D2), not a separate
annual-id path — consistent with FRG-PULL-004's baseline note (annual typing is a
B-milestone concern, not reimplemented here).

### 5. Refresh-trigger semantics (matched-but-missing → refresh path)

When matching finds a watched series (by id or name+alias) but **no local issue
record** for the pulled issue exists, the refresh command enqueues
**`refresh-series`** for that series (`triggered_by="pull-refresh"`), deduplicated
on the command queue (FRG-SCHED-003) so a busy pull week does not enqueue the same
series twice. The flow is deliberately **detect → refresh creates → policy wants →
search grabs**, with the pull side writing nothing to the issue:

1. Pull match detects the series but the issue is absent.
2. `refresh-series` reconciles metadata (FRG-META-008) and creates the issue.
3. The series' monitor-new-items policy (FRG-SER-007) decides monitored/wanted.
4. The normal backlog/auto search (FRG-SRCH-008/009) grabs it.

The pull entry's `matched_issue_id` is populated on the *next* pull refresh once
the issue exists (or opportunistically by the refresh completion, an
implementation detail). This is why "auto-want upcoming" needs no pull-side status
write (D1, D4) — a divergence from Mylar's `AUTOWANT_UPCOMING`.

### 6. Schedule defaults and throttle

- Built-in recurring task **`pull-refresh`** added to `BUILTIN_SCHEDULED_TASKS`,
  running the `pull-refresh` command. Default interval **4 h**
  (`pull_refresh_interval_seconds = 14400`), **minimum clamp** enforced by
  `register_task` (proposed floor **3600 s / 1 h** to protect the unofficial third
  party; documented). Mylar hardcodes 4 h; foragerr makes it configurable with a
  clamp.
- Each run fetches the **current + previous** release weeks (catch stragglers),
  per FRG-PULL-002.
- An **internal re-poll throttle** (default ~2 h, like Mylar) suppresses a fetch if
  the last successful fetch is recent — but the **manual force-run bypasses it**.
  Manual force-run is `POST /api/v1/system/task/pull-refresh` (FRG-API-014 /
  FRG-SCHED-007): enqueue-now, timer reset, dedup, returns the command id. No
  separate "recreate pull" endpoint (Mylar's `pullrecreate` collapses into
  force-run).
- The whole job is visible in job history (FRG-SCHED-008) and pushes status over
  the WS bus (FRG-SCHED-010), like every other command.

### 7. Trade-typing forward-compatibility (do not depend on, do not preclude)

Trade/collected-edition typing lands in **M3 change 5**. This change must not
depend on it and must not preclude the invariant **"trades never suppress
single-issue wanted"**. It does not, structurally: the pull backbone writes **no
single-issue wanted state at all** (D4) — wanting happens only via
refresh → monitor-policy (decision 5). So a trade appearing in a pull week can
never flip or suppress a single issue's wanted state through this machinery; when
change 5 adds a `booktype`/trade discriminator to entries, it slots onto the
`pull_entries` row and the matcher/surfacing without reworking storage. The
`match_type` + `entry_key` design leaves room for a future `booktype` column.

### 8. API surface for change 2

**One new read endpoint, `GET /api/v1/pull?week=<iso-week>` (FRG-API-019).**
Returns the metadata-derived weekly projection for the requested store-date week
(default: current week), using the standard paging envelope (FRG-API-006) and
standard resource/error conventions (FRG-API-002). Each row carries: the pull
entry fields, its `match_type`, and — for a linked entry — the matched issue's
**derived state** (missing/wanted, downloading, downloaded, unmonitored) computed
from issue + queue records (FRG-SER-004 / FRG-DL-008), or a "pending refresh" state
for a matched-but-not-yet-created issue. It exposes **no secret** (FRG-API-014
posture). This is the sole surface change 2 builds on; want/skip/search reuse the
existing issue endpoints, and force-refresh reuses FRG-API-014's task force-run.

## Risks / Trade-offs

- **[New outbound integration + untrusted JSON ingress]** → RISK-039 (realise
  mitigation) + RISK-025 pull arm (close via `external` egress profile). Bounded
  by: `external` egress profile (SSRF), mandatory timeouts, byte-capped stdlib
  JSON parse into a typed model, explicit error-code mapping, degraded-health on
  outage, and the source being *optional enrichment* over the local-primary view.
  Security-docs delta records this; no new residual risk expected.
- **[Source supplies wrong/ambiguous ComicVine IDs]** → IDs are *candidates*, not
  authority: an id match still passes the book-type guard, and a name match still
  passes sequence + date-window guards; anything ambiguous is stored `unmatched`,
  never linked. Pinned by the FRG-PULL-004 fixture (id match + valid name match +
  wrong-volume collision + unknown → exactly two links, two unmatched).
- **[Pull refresh hammering a series with duplicate `refresh-series`]** → command
  dedup (FRG-SCHED-003) collapses repeats; the re-poll throttle bounds fetch
  cadence; the min-interval clamp protects the third party.
- **[Torn per-week write on a mid-fetch failure]** → replace-on-refresh is one
  transaction (FRG-DB-007); a failed fetch leaves the prior week intact and marks
  health degraded — never a half-replaced week.
- **[Projection cost at library scale]** → `GET /pull?week=` is a bounded,
  week-scoped, indexed query joining a small per-week entry set to issues; paging
  envelope caps the response. Single-user scale; revisit only if profiling shows
  jank.

## Migration Plan

One forward alembic migration adds `pull_entries` (FRG-DB-002); a pre-migration
backup is taken automatically (FRG-DB-003). New config keys default to safe values
(`pull_enabled` may default off until a source is configured; `pull_source_url`
defaults to the documented walksoftly URL but no fetch runs unless enabled) and
migrate via FRG-DEP-004. Rollback = revert the merge; the table is additive and no
existing surface depends on it (change 2 is not yet merged).

## Open Questions

None blocking. Implementation-time calls, each with a stated default:

1. **`pull_enabled` default** — default **off** (no third-party traffic until the
   operator opts in), matching the "optional enrichment" posture; flip to on-with-
   default-URL only if the owner wants pull populated out of the box. *Orchestrator
   to confirm at the plan-mode gate.*
2. **Re-poll throttle window** — default ~2 h (Mylar parity); tune against the
   4 h schedule if it proves redundant.
3. **Min-interval clamp floor** — proposed 1 h; the owner may want it higher to be
   politer to the unofficial source.
4. **When `matched_issue_id` is backfilled** — on the next pull refresh vs
   opportunistically on `refresh-series` completion. Default: next pull refresh
   (simplest; keeps the matcher the single writer of the link).
