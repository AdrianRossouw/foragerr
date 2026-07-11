# m4-pull-experience

## Why

M4 chapter 5 — the final M4 chapter. The pull backbone (FRG-PULL-001..006) and
its read endpoint (FRG-API-019) shipped in M3, but the *screen* they were built
for never did: there is no Calendar in the nav, and the weekly release
projection is invisible to the user. This change ships the weekly pull
experience per design handoff v2 §4 — the most design-dependent screen, which
is why it was deliberately sequenced after the design refresh landed — and with
it the three approved M4 pull requirements (FRG-PULL-007..009).

## What Changes

- **Calendar screen (FRG-UI-018)** at `/calendar`, per design handoff §4: a
  date-grouped weekly **agenda** (deliberately NOT a 7-column grid — comics
  ship in one Wednesday drop). Toolbar: week nav (‹ This Week ›) + range
  label + publisher filter + `Following / All releases` segmented toggle; an
  info banner explaining the weekly-drop reality; per-day blocks (date
  numeral, accent bar, release cards with publisher-tinted cover spine,
  title, issue · publisher, state icon), "New Comic Day" badge on Wednesday,
  "Today" badge, "+N more shipping" note in Following scope, empty state.
  Calendar nav entry enters the sidebar in this change (shipped-screens rule,
  FRG-UI-023). Card state iconography is a projection of the entry's derived
  `state` — never pull-side status (D4).
- **Per-entry actions (FRG-PULL-007)**: entries linked to a library issue get
  want/skip (monitored toggle) and an immediate-search action, delegating to
  the canonical issue operations (`PUT /api/v1/issues/{id}`, `issue-search`
  command) — no pull-side writes, no new endpoints.
- **New-series surfacing (FRG-PULL-008)**: `match_type = "new_series"` entries
  render as a distinct "New this week" strip with a one-click add affordance
  that routes into the standard Add flow prefilled (the existing
  `prefillTerm` navigation-state seam). The system never auto-adds.
- **Future/solicited retention (FRG-PULL-009)**: the pull-refresh command's
  fetch window extends from {previous, current} to include the **next** ISO
  week when the source provides it, stored through the same idempotent
  per-week replace (FRG-PULL-003). Forward navigation on the screen then
  shows watched-series matches for the future week, marked not-yet-released.
- **Manual + docs**: new "Weekly pull / Calendar" section in
  `docs/manual/user/web-ui.md`; README screenshot set gains the calendar shot
  (FRG-PROC-017).

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `ui`: FRG-UI-018 elaborated from baseline to scenario depth (design-handoff
  agenda layout, week navigation, scope toggle, publisher filter, action
  affordances, new-series strip, future-week presentation).
- `pull`: FRG-PULL-007/008/009 elaborated from baseline to scenario depth.
  The wider fetch window needs no FRG-PULL-002 amendment — that requirement
  already reads "at least the current and previous release weeks"; the
  future-week behavior is carried entirely by FRG-PULL-009's scenarios.

No new requirement IDs are needed — all four (FRG-UI-018, FRG-PULL-007..009)
are already allocated and `approved` for M4 in the registry; they flip to
`implemented` at merge.

## Non-goals

- **No iCal feed** (Sonarr §7.1 has one) — OPDS is the only external read
  surface for now; an iCal export would be a new listener/requirement.
- **No pull-side status writes** — want/skip/search delegate to issue-level
  operations; the `pull_entries` store stays status-free (D4).
- **No auto-add of new series** (explicit FRG-PULL-008 divergence from Mylar).
- **No new pull source or fetch cadence changes** — same walksoftly source,
  same egress profile, same 4 h default interval; only the per-run week
  window widens.
- **No Creators nav entry** (M5; shipped-screens rule).
- **No month-grid or multi-week view** — the agenda is one week at a time
  with prev/next navigation, as designed.

## Impact

- **Backend** (small): `pull/commands.py` `_fetch_weeks()` gains the next
  week; `api/pull.py` untouched unless paging max needs a bump for
  all-releases weeks (decided in design). No schema/migration changes —
  `pull_entries` already keys by week.
- **Frontend** (bulk of the change): new `screens/calendar/` (screen + module
  css + tests), new `useWeeklyPull` query hook + `queryKeys.pull`, WS bridge
  invalidation case for pull events, Sidebar nav entry, routing in `App.tsx`.
  Reuses `useToggleIssueMonitored`, `useRunCommand('issue-search')`,
  `palettes.ts` publisher tints/accents (already shipped for this purpose),
  and the `AddSeriesNavigationState.prefillTerm` seam.
- **API surface**: no new endpoints; no auth changes.
- **Security**: no new attack surface — no new listener, no new outbound
  integration (the future-week fetch is the same hardened client against the
  same source), no new untrusted-input parser. No docs/security delta.
- **SOUP**: no dependency changes expected; `tools/soup_check.py` must stay
  green at the gate.
- **Docs**: manual §Calendar (new), README screenshot refresh.
- **Traceability**: registry status flips for the four IDs at merge; tagged
  tests per ID (pytest `@pytest.mark.req` / vitest name tags).

## Approval

Approved under the M4–M7 standing grant (Adrian, 2026-07-10: roadmap-reshape
approval, "keep going up to just before starting the auth milestone"), which
explicitly enumerates the M4 pull experience (FRG-UI-018 + FRG-PULL-007..009)
as in-scope for autonomous execution. Per-change gate obligations unchanged
(tiered review + Codex ninth angle before merge).
