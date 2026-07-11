# Design — m4-pull-experience

## Context

The M3 pull backbone left a deliberate seam: `GET /api/v1/pull?week=YYYY-Www`
(FRG-API-019) returns the merged projection (library-primary rows + stored
pull-source rows with `match_type` / `state`), and its spec notes say the
screen is "three client calls with no server-side navigation state". The
frontend has an established screen pattern (`screens/<name>/` triple), React
Query hooks in `api/hooks.ts`, WS-driven invalidation in
`WebSocketBridge.tsx`, and — shipped ahead of need — publisher tint/accent
maps in `theme/palettes.ts` documented "for calendar spines". The design
handoff v2 §4 fixes the visual: a date-grouped agenda, Following-scoped by
default.

## Goals / Non-Goals

**Goals**: ship the Calendar screen to design; wire want/skip/search through
canonical issue operations; surface new-series debuts with a prefilled add
hand-off; widen the fetch window to the next ISO week.

**Non-goals**: iCal feed, month grid, pull-side writes, auto-add, new pull
sources, paging redesign of FRG-API-019.

## Decisions

1. **Week aggregation client-side, one query key per week.**
   `useWeeklyPull(week)` fetches `pageSize=200, sortKey=release_date`; if
   `totalRecords > 200` it fetches the remaining pages and concatenates
   before returning (a single React Query `queryFn`, key
   `queryKeys.pull.week(week)`). Rationale: the screen always needs the whole
   week (day-grouping, counts, banner math are whole-week properties);
   server-side day-grouping or a bigger page cap would change FRG-API-019 for
   one consumer. Alternative rejected: raising the endpoint's max pageSize —
   touches a shipped API contract for no cross-client benefit.

2. **ISO week math is a small tested util, no new dependency.**
   `frontend/src/utils/isoWeek.ts`: `currentIsoWeek()`, `addWeeks(week, n)`,
   `weekRangeLabel(week)`, `weekDates(week)` — pure functions over the ISO
   8601 week rules (Thursday rule), unit-tested across year boundaries
   (W52/W53→W01). Alternative rejected: date library (new SOUP entry for
   ~40 lines of arithmetic).

3. **Screen structure mirrors the handoff's component tree.**
   `screens/calendar/CalendarScreen.tsx` (toolbar, banner, strip, agenda) +
   `CalendarScreen.module.css` + `CalendarScreen.test.tsx`; card and
   day-group stay internal components of the screen file unless size forces a
   split (match `wanted/` precedent). Publisher spine colors via
   `publisherTint()`/`publisherAccent()`; everything else via `tokens.css`
   vars (token-name audit test forbids brand-named tokens).

4. **Scope/publisher filters are client-side view state.**
   The endpoint has no scope/publisher params and doesn't need them — the
   week is already fully loaded (Decision 1). "Following" = entries with
   `series` link or `state == pending_refresh`; hidden-count notes are
   arithmetic over the unfiltered week. URL carries `?week=` only (shareable
   position, back/forward works); scope + publisher are component state
   defaulting to Following/All-publishers.

5. **Actions reuse the Wanted screen's seams verbatim.**
   Want/skip → `useToggleIssueMonitored` (single-issue PUT); search →
   `useRunCommand('issue-search', {series_id, issue_id})` +
   `useWatchedCommand` → on terminal status invalidate
   `queryKeys.pull.all()` and wanted/issues keys. Unlinked entries render no
   action cluster (FRG-PULL-007 scenario 3). The pull endpoint stays
   read-only.

6. **New-series strip is a filter, not a new resource.**
   `matchType === 'new_series'` rows for the viewed week render in a strip
   above the agenda (they also stay out of the day groups to avoid double
   counting — the agenda proper renders non-new-series rows). Add affordance:
   `navigate('/add', { state: { prefillTerm: seriesName } })` — the existing
   `AddSeriesNavigationState` seam the header quick-search uses. Alternative
   rejected: carrying CV ids into the add flow to pre-select a candidate —
   source-supplied ids are match *candidates* only (FRG-PULL-004); letting
   the standard lookup rank candidates keeps one trust path.

7. **Backend delta is confined to the fetch window.**
   `pull/commands.py::_fetch_weeks()` returns `[previous, current, next]`.
   The existing per-week error discipline (619 skips the week; transport
   failure = outage) already gives FRG-PULL-009's skip semantics; the only
   nuance is an **empty future-week payload is a skip, not an outage** —
   asserted by a tagged test. No schema change: `pull_entries` keys by week.

8. **WS invalidation: piggyback on existing events + command completion.**
   Card state derives from issue/queue records, and `WebSocketBridge`
   already invalidates on issue/queue/series events — add
   `queryKeys.pull.all()` to those cases plus pull-refresh command
   completion. No new WS event type; the backend emits nothing new.

## Risks / Trade-offs

- [Giant all-releases week exceeds one page] → page-aggregation loop in the
  hook, capped and tested; worst realistic week ≈ 150–300 rows = 1–2 extra
  requests.
- [ISO week math drift vs backend `date.fromisocalendar`] → util tests pin
  the same fixture weeks the backend tests use (incl. year-boundary weeks).
- [Source may not publish future weeks at all] → FRG-PULL-009 scenario 3
  makes "skip quietly" the specified behavior; the screen's future week
  still renders the library-primary half.
- [Double-render of a new-series row in strip + agenda] → agenda explicitly
  excludes `new_series` rows; a test asserts a fixture row appears exactly
  once.

## Migration Plan

No migrations, no config, no new endpoints. Ships as one change branch;
rollback = revert the merge. Registry rows for FRG-UI-018/FRG-PULL-007..009
flip `approved → implemented` in the same change.

## Gate-accepted divergences from the handoff

Recorded at the m4-pull-experience review gate (frontend-fidelity angle):

- **Toolbar composition**: the handoff (§4, dc.html 526–542) shows one row
  (week nav · range · spacer · publisher · scope). The implementation keeps
  publisher/scope in the app-level Toolbar (with the screen title, matching
  every other shipped screen) and puts week nav + range in a bar below.
  Shell consistency wins over mock parity — accepted.
- **Card right edge**: the handoff card carries a single state icon; linked
  cards additionally carry want/skip + search buttons. That is FRG-PULL-007
  extending the static mock — required behavior, accepted.
- **Withdrawn future solicitations**: an empty future-week payload is a skip
  (never a store), so a withdrawn entry can persist until the source next
  returns data for that week or the week rolls current (≤ ~2 weeks). The
  alternative (trusting empty as authoritative) reintroduces the clobber
  risk FRG-PULL-009 exists to prevent — accepted, code-commented.

## Open Questions

_None blocking. If the live source turns out to reject future-week requests
with an undocumented code rather than 619/empty, the skip branch widens to
treat any single-future-week failure as a skip (current/previous handling
unchanged) — a one-line containment decided at implementation time and
covered by the same tagged test._
