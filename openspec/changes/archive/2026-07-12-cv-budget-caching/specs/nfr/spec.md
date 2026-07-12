# Delta: nfr — cv-budget-caching

## MODIFIED Requirements

### Requirement: FRG-NFR-004 — ComicVine rate limiting

The system SHALL enforce a client-side ComicVine rate limit shared across ALL concurrent operations (default: max 1 request per 2 s, configurable with a floor), and on rate-limit/ban signals SHALL back off, mark the ComicVine backend degraded, and NOT retry in a tight loop. The politeness budget SHALL additionally bound hour-scale volume per ComicVine resource path (FRG-META-016): request spacing alone must never be able to exhaust ComicVine's documented per-path hourly allowance.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §1.3 and §3.1 (fixed sleep, unlocked concurrency, no Retry-After handling — weaknesses to fix), §5 (candidate requirement); ComicVine rate-limit documentation + owner live usage data (2026-07-12).
- **Notes**: Divergence from Mylar: a real shared limiter (async token/lock), not a per-call sleep. CV client behavior (endpoints, pagination) is META's; NFR owns the politeness budget. Amended by cv-budget-caching: the budget is two-dimensional (velocity + hourly per path); FRG-META-016 owns the budget mechanics, this requirement owns the politeness posture.

#### Scenario: Limiter is process-global across all call sites

- **WHEN** concurrent ComicVine operations spanning search, volume, issue, and cover call sites are driven simultaneously
- **THEN** observed inter-request wire times at the HTTP layer are serialized to at least the configured minimum interval across all call sites combined, never per-call-site independent spacing

#### Scenario: 429 with Retry-After is honored

- **WHEN** ComicVine returns a 429 response carrying a `Retry-After` header
- **THEN** the limiter suppresses further ComicVine requests until at least the Retry-After delay has elapsed and does not retry in a tight loop

#### Scenario: Ban/degraded state is observable via health

- **WHEN** a simulated ComicVine ban/rate-limit signal is received
- **THEN** the ComicVine backend is marked degraded in the exposed component health, and further calls are suppressed for the cool-down window rather than reissued immediately

#### Scenario: Configured interval below the floor is clamped

- **WHEN** the limiter interval is configured below the documented floor
- **THEN** the effective interval is clamped to the floor (with a warning) and enforced spacing never drops below that documented minimum

#### Scenario: Sustained-rate traffic cannot exhaust a per-path hourly allowance

- **WHEN** a workload issues requests on one resource path at the full velocity the spacing gate permits for over an hour
- **THEN** admissions on that path stop at the configured soft ceiling (≤200) with typed local refusals and health visibility, so ComicVine's server-side per-path limit is never reached from inside foragerr
