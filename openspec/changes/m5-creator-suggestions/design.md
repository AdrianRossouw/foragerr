# Design — m5-creator-suggestions

## Context

The last M5 chapter. Integration surfaces were live-probed before any
code (the day's lesson applied): `person/4040-{id}/` serves
`volume_credits` stubs (id+name); `volumes/?filter=id:a|b|c` batch-hydrates
full rows. Stored credits already carry `cv_person_id`, so no person
search is needed. The autonomous grant ends when this merges (owner
reviews M5, then kicks off M6 in a new session).

## Goals / Non-Goals

**Goals**: bibliography fetch/cache via the command backbone; read
sub-resource with stale-while-revalidate; the profile "More from" section
with add hand-offs. **Non-goals**: auto-add; feeds/notifications; person
images; follow-priority refresh.

## Decisions

1. **Command does CV, API serves cache** — mirrors every acquisition-side
   pattern in the codebase (pull, backfill): the GET enqueues a
   deduplicated `creator-bibliography-fetch` when cold/stale and never
   touches ComicVine itself, preserving FRG-API-023's discipline.
2. **Cache table + stamp, replace-per-creator** — `creator_bibliography`
   (creator FK CASCADE, cv_volume_id, sanitized title/publisher,
   start_year, count_of_issues; unique (creator_id, cv_volume_id)) +
   `creators.bibliography_fetched_at`; migration 0018 (keystore → 0019).
   In-library exclusion is a read-time anti-join on
   `series.cv_volume_id` — a volume added after caching disappears from
   suggestions without a refetch.
3. **Cap 24, newest start_year first** — a prolific creator costs ~3 CV
   requests (person + 1-2 hydration batches of 12); config knob deferred
   until demand (constant with a comment).
4. **TTL 7 days, stale-while-revalidate** — profile stays usable when the
   third party is flaky; WS command completion invalidates the client
   query.
5. **Add hand-off reuses the standard flow** — navigate('/add', state
   {prefillTerm: volumeName}); direct cvVolumeId preselection is a nice-to
   -have only if the Add screen's existing seams support it without
   surgery (worker's judgment; never bypass the add-config step).
6. **Fixtures mirror the probed shapes** with client tests pinning both
   request paths (`person/4040-`, the pipe filter) — the anti-masking
   rule.

## Risks / Trade-offs

- [Bibliography quality: CV stubs include everything (variants, foreign
  editions)] → newest-first + cap keeps it presentable; refinement waits
  for real feedback.
- [Fetch triggered by any profile visit (not just followed creators)] →
  cap + TTL + dedup bound the cost; acceptable for single-operator.
- [Stale in-library rows in cache] → excluded at read time (Decision 2).

## Migration Plan

Migration 0018: cache table + stamp column; forward-only; no backfill
(empty cache = `never`, fetched on first profile view).

## Open Questions

_None blocking._
