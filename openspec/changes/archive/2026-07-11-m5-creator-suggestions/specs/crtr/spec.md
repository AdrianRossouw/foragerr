# Delta: crtr — m5-creator-suggestions

## ADDED Requirements

### Requirement: FRG-CRTR-005 — External creator bibliography fetch and cache

The system SHALL fetch a creator's broader ComicVine bibliography via a
`creator-bibliography-fetch` command on the command backbone (deduplicated
per creator, rate-gated through the shared client): the person detail
(`person/4040-{cv_person_id}/`, `field_list` limited to id/name/
volume_credits — live-verified shape) yields volume stubs, from which the
command hydrates a **bounded** slice (documented cap, default 24) of
volumes **not already in the library**, newest `start_year` first, via the
batched volumes filter (`volumes/?filter=id:a|b|c`), and replaces the
creator's rows in a `creator_bibliography` cache table (forward-only
migration) stamping `bibliography_fetched_at` on the creator. All strings
pass the shared CV sanitizer (FRG-META-014). A fetch failure SHALL leave
any previously cached bibliography intact and the stamp unset for retry;
the command SHALL never add a series, enqueue a search, or write any
series/issue/follow state.

- **Milestone**: M5
- **Source**: design handoff §8 ("More from <name>"); comics-domain
  direction 2026-07-05 (subscribe → suggestions, never auto-add); live CV
  probes 2026-07-11 (person/4040 + pipe-filter hydration, in-session).
- **Notes**: Migration 0018 claimed at proposal time (keystore shifts to
  0019). TTL/staleness is the read side's concern (FRG-API-024); the
  command just replaces-and-stamps. The cap bounds a prolific creator
  (231 stubs for Willingham) to ~2-3 CV requests per fetch.

#### Scenario: Fetch hydrates a bounded, not-in-library, newest-first slice

- **WHEN** the command runs for a creator whose person detail lists more
  volume stubs than the cap, some already in the library
- **THEN** in-library volumes are excluded, the newest remaining volumes
  up to the cap are hydrated in batched requests through the rate gate,
  and the cache rows replace that creator's previous rows atomically

#### Scenario: Failure preserves the previous cache

- **WHEN** the person or hydration fetch fails mid-run
- **THEN** the creator's previously cached bibliography rows survive
  untouched, the stamp is not advanced, and the command records the
  failure without raising

#### Scenario: The fetch acquires nothing

- **WHEN** a bibliography fetch completes
- **THEN** no series exists that did not exist before, no search or
  download was enqueued, and no follow/monitored flag changed
