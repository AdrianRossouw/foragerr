# Proposal: wanted-count-consistency

## Why

There are two different definitions of "missing" in the codebase and they
disagree. `series_statistics.missing_count`
(`backend/src/foragerr/library/repo.py`) is computed as `issue_count -
file_count` — **every** fileless issue, including unreleased/future and
unmonitored ones — while `wanted_issues()` (FRG-SER-004) correctly counts only
`series.monitored AND issue.monitored AND released AND no file`. So a series
with solicited future issues over-reports "missing", and the series-card /
badge numbers disagree with what the Wanted screen actually lists. This is the
root cause of the flagged "Wanted-badge over-count" demo finding, surfaced again
when the refreshed screenshots showed nav badges that don't match their screens.

Separately, the sidebar nav **count** badges mislead by construction: they count
different things — and different *units* — than the screens they point at. The
Wanted badge counts *series that have missing issues* (e.g. 4) while the Wanted
screen lists missing *issues* (dozens); the Sources badge counts *all* unreviewed
new entitlements (comic + non-comic, e.g. 6) while the Sources screen defaults to
the comic view (e.g. 3).

## What Changes

- **Single definition of "missing" (the bug fix).** `series_statistics.missing_count`
  SHALL be derived from the same wanted-predicate as `wanted_issues()`
  (monitored + released + fileless), so series cards, statistics, and the Wanted
  screen always agree and unreleased/unmonitored issues are never counted as
  missing. One source of truth for "missing", aligned to FRG-SER-004.
- **Drop the nav count badges except active work** (Sonarr/Radarr precedent:
  nav badges signal active work only — owner decision 2026-07-14, full minimal):
  - Remove the **Wanted** count badge — missing counts live on the Wanted page,
    in issue units.
  - Remove the **Sources** unreviewed-new count badge; **keep** the amber `!`
    expiry indicator (a state signal that needs attention, not a count).
  - Remove the **Comics** library-size count badge.
  - **Keep only** the Queue/Activity active-download badge — the one
    *arr-sanctioned nav count (work in progress).
- No stored counters change — `missing_count` stays derived-at-request-time
  (FRG-SER-009's existing invariant).

## Capabilities

### Modified Capabilities

- `ser` — **FRG-SER-009** (Series statistics): pin `missing_count` to the
  wanted-predicate so there is a single definition of "missing"; add an
  invariant scenario proving it excludes an unreleased and an unmonitored issue
  and equals the `wanted_issues()` count for the series.
- `ui` — **FRG-UI-023** (Application shell): the sidebar nav carries only the
  Activity/Queue active-work count badge; the Comics and Wanted count badges are
  removed. **FRG-UI-029** (Sources screen): the Sources nav badge is the expiry
  `!` only, with no unreviewed-new count.

### New Capabilities

None.

## Non-goals

- Changing the Wanted screen's list contents or the `wanted_issues()` predicate
  itself (it is already correct — this aligns statistics *to* it).
- Reworking the Sources manage view's on-page count line / All-New-Matched-Ignored
  filter (those are correct on-page counts; only the nav badge is dropped).
- Removing the Queue active-download badge (kept) or the Sources expiry `!` (kept).

## Security impact

None. Internal statistics aggregation and sidebar rendering only — no new
listener, parser of untrusted input, credential, or outbound integration.
`docs/security/` unchanged.

## Manual impact

`docs/manual/`: if the Wanted or Sources sections describe the nav count badges,
update them to match (Wanted count now lives on its page; Sources nav shows only
the expiry indicator). README screenshots already reflect the current UI; the
badge removal will be picked up on the next screenshot refresh.

## Registry allocations

None — this modifies existing requirements (FRG-SER-009, FRG-UI-023, FRG-UI-029).
No new IDs are allocated.

## Approval

Approved in-session by Adrian 2026-07-14: fix the missing-count definition + drop
the nav count badges to **full Sonarr-minimal** (keep only the Queue active-work
badge and the Sources expiry `!`); "another 0.9.x release cycle". Implementation
proceeds under FRG-PROC-009.
