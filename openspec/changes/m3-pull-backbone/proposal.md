## Why

M2 is complete (v0.2.8): the library owns its files, the daily surfaces (History,
Wanted, System/Tasks, backups) are live, and the SCHED command backbone +
`refresh-series` chain + wanted/missing machinery all exist and are proven. M3
turns foragerr comics-native, and the first thing a comics reader wants that a
generic downloader does not have is a **weekly pull list**: "what shipped this
week that I care about, and do I have it yet?"

The PULL area baseline (FRG-PULL-001..009, approved in the requirements baseline)
is deliberately Sonarr-shaped, not Mylar-shaped: **local metadata is the pull
list**, and the unofficial third-party weekly feed only *enriches and
cross-checks* it (FRG-PULL-001 Notes). That inversion is the whole reason the
feature keeps working when the third party is down — but it also means the pull
list is mostly **machinery** (a per-week store, a fetch client, a matcher, a
refresh trigger, a schedule) sitting under one screen. Building the machinery and
the screen in one change would be a large, poorly-parallelisable blob that mixes
a new outbound integration and a correctness-critical matcher with React.

So M3's pull work is split into two composed changes. **This change
(m3-pull-backbone, M3 change 1)** builds everything below the screen: the
metadata-derived weekly projection, the external pull-source fetch, idempotent
per-week storage, matching to the library, the refresh trigger for missing
pulled issues, the scheduled + manual refresh, and the **minimal read API** the
screen will consume. **m3-pull-experience (M3 change 2)** builds the screen
itself (FRG-UI-018) and the per-entry actions on top of that API (FRG-PULL-007
pull-view actions, FRG-PULL-008 new-series surfacing, FRG-PULL-009 future
releases). The split is justified in `design.md` §1.

### Why this split composes cleanly

Backbone owns **data + jobs + one read endpoint**; experience owns **the screen +
actions**, and every experience action delegates to a *canonical* operation the
backbone or an existing area already provides:

- "want/skip" (FRG-PULL-007) → the existing issue monitored-toggle
  (FRG-API-004) on the *linked* issue — never a pull-side status write (D4).
- "search now" (FRG-PULL-007) → the existing issue-search command
  (FRG-SRCH-008/014).
- "add new series" (FRG-PULL-008) → the existing add flow (FRG-SER-005).
- "future/forward nav" (FRG-PULL-009) → the same `GET /pull?week=` this change
  ships, pointed at a future week.

Because pull entries **carry only a link to library issues, never their own
wanted/downloaded status** (FRG-PULL-003 Notes, D4), the experience change adds
no new state model — it is a projection over issue + queue state the backbone and
existing areas already own. The backbone therefore needs no knowledge of the
screen, and the screen needs no new backbone beyond the read endpoint.

## What Changes

- **Metadata-derived weekly release view (MODIFIED FRG-PULL-001)** — a
  library-primary projection: given a store-date week, the issues of watched
  series whose store date falls in that week, each with its derived state
  (missing/wanted, downloading, downloaded, unmonitored) computed from issue +
  queue records. Works with **no pull source configured** (Sonarr calendar
  model). This change delivers the projection and its read API (below); the
  *screen* that renders it is FRG-UI-018 in change 2.

- **External pull-source fetch (MODIFIED FRG-PULL-002)** — a configurable
  outbound fetch of weekly release data (default: the walksoftly /
  League-of-Comic-Geeks-derived JSON API named in the baseline), covering the
  current + previous release weeks, over the **existing hardened egress factory**
  (`security` external profile, FRG-SEC-001) with mandatory timeouts, handling
  the source's documented error codes (619 bad-date / 522 backend-down /
  666 client-update), treating the JSON as **untrusted input** (FRG-NFR-012), and
  surfacing source-outage / stale-data as a **health item** (FRG-NFR-011 /
  FRG-API-014) rather than failing silently. This is the change's one new
  outbound integration → security-docs delta (see Impact).

- **Idempotent per-week storage (MODIFIED FRG-PULL-003)** — a new `pull_entries`
  table keyed by (week, entry identity) with a per-week **replace-on-refresh**
  strategy so repeated fetches of the same week are idempotent; each entry
  records publisher, series name, issue number, source-supplied ComicVine IDs
  when present, and release date, plus a **link** to a library issue (nullable) —
  never its own wanted/downloaded status.

- **Matching pull entries to the library (MODIFIED FRG-PULL-004)** — reuses the
  existing series/issue identity machinery (`library/matching.py`): match by
  ComicVine id (series + issue) first, else a **guarded** name match (normalized
  series-name/alias equal AND issue number a plausible next-in-sequence
  0 ≤ delta < 3 AND release date within the pull week ±2 days); ambiguous or
  unknown entries are recorded **unmatched**, never guessed.

- **Refresh trigger for missing pulled issues (MODIFIED FRG-PULL-005)** — when a
  pull entry matches a watched series but no local issue record exists, enqueue
  the existing **`refresh-series`** command (dedup on the command queue,
  FRG-SCHED-003) so metadata creates the issue and the series' monitor-new-items
  policy decides whether it becomes wanted. Detection here, creation by refresh,
  wanting by policy, grabbing by the normal search pipeline — **no pull-side
  status write** (D1, D4).

- **Scheduled and manual pull refresh (MODIFIED FRG-PULL-006)** — a new
  `pull-refresh` command (fetch → store → match → trigger) registered as a
  built-in recurring task on the existing IntervalScheduler (default 4 h, minimum
  clamp to protect the third party), plus a **manual force-refresh** that reuses
  the existing task force-run surface (`POST /api/v1/system/task/pull-refresh`,
  FRG-API-014 / FRG-SCHED-007) and bypasses the internal re-poll throttle.

- **Pull/weekly resource endpoint (FRG-API-019, NEW)** — `GET /api/v1/pull?week=`
  returns the metadata-derived weekly projection for a given store-date week
  (defaulting to the current week), each row carrying the matched library issue's
  derived state or, for a matched-but-not-yet-created entry, its pending state.
  This is the **minimal read API** change 2 builds the screen and its
  prev/current/next navigation on; it never exposes any secret. Manual
  force-refresh is NOT a new endpoint — it reuses FRG-API-014's task force-run,
  exactly as "back up now" did.

## Capabilities

### New Capabilities

- `api`: FRG-API-019 (pull/weekly resource endpoint — the metadata-derived weekly
  projection read surface change 2 consumes).

### Modified Capabilities

- `pull`: FRG-PULL-001..006 elaborated from baseline SHALL + coarse acceptance to
  implementable requirements with scenario-level acceptance (the pull backbone:
  projection, fetch, storage, matching, refresh trigger, schedule).

## Impact

- **Code**: backend only. New `pull/` package: `models.py` + `repo.py` + a
  migration for `pull_entries` (rides FRG-DB-002 versioned migrations,
  FRG-DB-008 typed schema — no DB *requirement* changes); `source.py` (the fetch
  client over the `security` external egress profile, error-code mapping, health
  hook); `matching.py` (thin adapter reusing `library/matching.py`);
  `projection.py` (the metadata-derived weekly view); `commands.py` (the
  `pull-refresh` command + built-in task registration in `commands/__init__`);
  `api/pull.py` (the `GET /pull` route). New config keys on `config.py`
  (`pull_source_url`, `pull_refresh_interval_seconds` with a min clamp,
  `pull_enabled`). No frontend, no new screen — that is change 2.

- **DB**: one new table `pull_entries` under the existing migration + typed-schema
  discipline (FRG-DB-002/008). It is governed by FRG-PULL-003, so no DB-area
  *requirement* is modified. No change to existing tables.

- **Security docs** (FRG-PROC-006): **a security-docs delta IS required.** The
  external pull-source fetch (FRG-PULL-002) is the change's one new outbound
  integration and one new untrusted-content ingress — both already *anticipated*
  in the threat model (untrusted input #5) and risk register: **RISK-039**
  (external weekly-pull JSON source as outbound dependency + untrusted ingress,
  Mitigate, L/L) and the still-open **pull-source arm of RISK-025** (SSRF via a
  config-supplied source host). This change moves both from anticipated to
  live: RISK-039's mitigation is realised (mandatory timeouts, documented
  error-code handling, degraded-health surfacing, untrusted-JSON treatment), and
  RISK-025's pull arm closes via the `security` external egress profile
  (FRG-SEC-001) applied to the configurable source URL. A STRIDE note on the pull
  fetch is added to `docs/security/threat-model.md`, and RISK-039 + RISK-025 are
  updated with an implemented-status entry. **No new risk id is expected** —
  RISK-039 already reserves this integration. (If implementation elects a
  proxy-per-source or any egress choice beyond the shared factory, that would be a
  new decision requiring its own row — not anticipated.)

- **Manual** (FRG-PROC-011): **admin-facing only.** The pull backbone adds
  operator-configurable settings and one scheduled task, so
  `docs/manual/admin/configuration.md` gains a "Weekly pull" subsection (source
  URL, refresh interval + its clamp, enable/disable, and the degraded-source
  health item) and the scheduled-tasks list gains `pull-refresh`. **No
  user-facing manual change** in this change: there is no pull *screen* yet — the
  `docs/manual/user/` pull-list section lands with the screen in change 2
  (declared there). README labelling: the pull list stays a "planned/partial"
  feature until change 2 completes the surface.

- **Dependencies / SOUP** (FRG-PROC-012): **none anticipated.** The fetch reuses
  the existing `httpx`-based egress factory; JSON parsing uses the stdlib. If
  implementation adds any dependency (e.g. a JSON-schema validator for the source
  payload), `docs/security/soup-register.md` MUST be updated in this same change
  and `tools/soup_check.py` kept at exit 0 (default expectation: no SOUP change).

## Non-goals

- **No pull screen and no per-entry actions** — FRG-UI-018 (the weekly view),
  FRG-PULL-007 (want/skip/search from the view), FRG-PULL-008 (new-series
  surfacing + add), and FRG-PULL-009 (future-release forward nav) are
  m3-pull-experience (change 2). This change stops at the read API + jobs.

- **No auto-add of series and no auto-want write from the pull side.** New-series
  surfacing is a *change-2* screen affordance; auto-want happens only through the
  refresh → monitor-policy path (FRG-PULL-005), never a pull-table status flip
  (deliberate divergence from Mylar's `future_check` auto-add and
  `AUTOWANT_UPCOMING`).

- **No trade/collected-edition typing or suppression logic.** Trade typing lands
  in M3 change 5; this change neither depends on it nor precludes it — pull
  entries never write single-issue wanted state, so the invariant "trades never
  suppress single-issue wanted" is not violated here (it is simply not yet
  *enforced* against trade entries, which arrive with change 5). Design §7.

- **No second/fallback pull source, no PreviewsWorld scrape, no weekly folder,
  no one-off (unwatched) pull downloads, no mass-publisher auto-add** — Mylar
  features deliberately excluded (see FRG-PULL-008/009 Notes and design §2).

- **No new SCHED or DB requirement.** The `pull-refresh` task rides
  FRG-SCHED-006/007 unchanged; the `pull_entries` table rides FRG-DB-002/008
  unchanged — this change modifies neither area's requirements.

## Approval

Adrian pre-approved this change on 2026-07-06 under the standing M2/M3
FRG-PROC-009 grant. His words, verbatim:

> keep going with m2/m3 and all their related changes as you go. I'll come check in later

Recorded per the standing-grant model already used across M2; m3-pull-backbone
(M3 change 1) falls squarely within that grant's scope. A plan-mode gate for the
implementation phase is still Adrian's to open per FRG-PROC-009.
