# Design: wanted-count-consistency

## Context

`wanted` is a derived predicate (FRG-SER-004): a series is "wanted" on an issue
when `series.monitored AND issue.monitored AND released AND no issue_file`.
`wanted_issues()` in `backend/src/foragerr/library/repo.py` implements exactly
that, and the Wanted screen (FRG-API-012 / FRG-UI-011) is a paged view over it.

But `series_statistics()` in the same file computes `missing_count = max(issue_count
- file_count, 0)` — a *different* definition that ignores both the `monitored` and
`released` filters. On a library of old, fully-released, all-monitored issues (like
the PD demo) the two roughly coincide, so the drift is invisible; on a modern
ongoing series with solicited future issues it over-counts, claiming unpublished
issues are missing. The series card `have/total`, the missing badge, and the
Wanted page then disagree.

The sidebar (FRG-UI-023) renders nav count badges; `SourcesNavBadge` (FRG-UI-029)
renders the Sources badge. Both count something other than what their target
screen shows by default, producing the "6 vs 3" and "4 vs dozens" mismatches.

## Goals / Non-Goals

**Goals:**
- One definition of "missing" everywhere, equal to the wanted set for a series.
- Nav badges that never mislead — drop the count badges whose numbers can't be
  reconciled against their screens at a glance.

**Non-Goals:**
- Touching `wanted_issues()` (already correct); reworking on-page counts; removing
  the Queue active-work badge or the Sources expiry `!`.

## Decisions

### 1. `missing_count` = the wanted-predicate count (single source of truth)
Rewrite `missing_count` in `series_statistics()` to count issues satisfying the
**same** predicate as `wanted_issues()` for that series: issue monitored AND
series monitored AND released (`store_date`/`cover_date` ≤ as_of, or both null) AND
no `issue_file`. Prefer to derive it from the shared predicate rather than
duplicate the SQL — factor the released/monitored/no-file condition so
`wanted_issues()` and `series_statistics()` cannot drift again (a helper predicate
both call, or `series_statistics` counts over the `wanted_issues()` selectable
filtered to the series). `have/total` (`file_count`/`issue_count`) stay as-is —
they are honest raw totals; only `missing_count` gains the wanted semantics.
`as_of` threading already exists on both functions, so "released" is evaluated
against the same clock.

Consequence: `missing_count` no longer equals `issue_count - file_count` in
general (an unreleased fileless issue is not missing; an unmonitored one is not
missing). The FRG-SER-009 scenario that forbids stored counters is unchanged — it
stays derived-at-request-time.

### 2. Nav count badges → active work only (FRG-UI-023)
Remove the `wanted` and `series` (Comics library-size) badge kinds from the
sidebar; keep only the Activity/Queue (queue length) badge. The Wanted and Comics
nav items keep their icon/label and active treatment but carry no count. Rationale
(owner decision 2026-07-14, full Sonarr-minimal): the Wanted badge counted *series
with missing* — a different unit from the page's *missing issues* — and no single
number reads correctly against it; Sonarr/Radarr badge only active work (the queue).
Missing counts live on the Wanted page, in issue units; the library size is
evident on the Comics page. Queue stays because in-progress work is the one
at-a-glance nav count *arr keeps.

### 3. Drop the Sources unreviewed-new count, keep the expiry `!` (FRG-UI-029)
`SourcesNavBadge` keeps the amber `!` when any connected store is expired (the
important, unambiguous attention signal) and drops the `useSourcesNewCount` path.
The unreviewed-new count counted all classifications while the manage view defaults
to comic-only, so the badge and screen disagreed; the on-page count line and
All/New/Matched/Ignored filter already convey pending review accurately where the
scope is visible.

### 4. Comics badge — dropped (owner decision)
Approval chose the fully Sonarr-minimal nav: the Comics library-size badge is
removed too. Only the Queue active-work badge and the Sources expiry `!` remain on
the nav. (The library size is still visible on the Comics page header.)

## Risks / Trade-offs

- **Behaviour change in a shipped number.** `missing_count` will drop for any
  series with unreleased or unmonitored fileless issues. That is the intended
  correction, but it is user-visible on series cards; the CHANGELOG calls it out.
- **Removing badges is a visible UX change.** Operators who read the Wanted badge
  lose an at-a-glance number; the mitigation is that the number was misleading and
  the accurate count is one click away on the page. Reversible if disliked.
- **Predicate-sharing refactor.** Factoring the wanted predicate so both callers
  use it is the safe way to prevent re-drift; the risk is a subtle SQL difference
  between the count and the list — covered by a test asserting `missing_count`
  equals the length of `wanted_issues()` filtered to the series across
  released/unreleased/monitored/unmonitored fixtures.
