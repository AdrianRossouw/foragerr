# Delta: pull — pull-enabled-default

## MODIFIED Requirements

### Requirement: FRG-PULL-002 — External pull-source fetch

The system SHALL fetch weekly release data from a **configurable** external source
(default: the walksoftly / League-of-Comic-Geeks-derived JSON API), covering at
least the current and previous release weeks per run. The fetch SHALL use the
shared hardened egress factory's **external** profile (FRG-SEC-001) applied to the
configured source URL — refusing loopback/private/link-local targets and applying
mandatory timeouts with auto-redirects disabled (FRG-NFR-006) — and SHALL treat
the response body as **untrusted input** (FRG-NFR-012), parsing it under a byte cap
into a typed entry model. The system SHALL handle the source's documented error
codes (619 bad-date, 522 backend-down, 666 client-update-required): a 619 skips the
affected week with a logged warning; a 522/666 or any transport failure is treated
as a source outage that **leaves the previously stored week intact** and marks the
pull source **degraded** in the health surface (FRG-NFR-011 / FRG-API-014) rather
than failing silently or discarding good data. The source SHALL be **enabled by
default** (owner decision 2026-07-11) so a fresh install's weekly view carries
external data without configuration; it remains fully optional — when disabled
(`pull_enabled=false`) or unconfigured, no fetch occurs, no third-party traffic is
issued, and FRG-PULL-001 still functions.

- **Milestone**: M3 (default flipped to enabled in pull-enabled-default,
  2026-07-11)
- **Source**: mylar-feature-surface.md §1 (walksoftly API, error codes 619/522/666,
  two-week window, stale-data behavior); capability map PULL; owner decision
  2026-07-11 (`docs/process/decisions.md`).
- **Notes**: Single unofficial third-party dependency — treated as optional
  enrichment over the local-primary view (FRG-PULL-001). Source URL configurable
  because the service is unofficial and has moved. Security (FRG-PROC-006): this is
  the change's one new outbound integration + untrusted-content ingress —
  RISK-039 (integration) mitigation realised here, and the pull-source arm of
  RISK-025 (SSRF) closed via the external egress profile. Source-supplied ComicVine
  IDs are recorded as *candidates* only; they are not trusted as match authority
  (FRG-PULL-004 still guards them). Only this one source is supported — the legacy
  PreviewsWorld scrape / flat-file paths are not reimplemented. Default-on posture
  (2026-07-11): every install now issues scheduled traffic to the unofficial source
  by default; owner-accepted on RISK-039, opt-out preserved.

#### Scenario: Source outage leaves stored data intact and marks health degraded

- **WHEN** a pull refresh runs and the source returns a 522-equivalent backend-down
  response (or the transport fails)
- **THEN** the previous fetch's stored week is left byte-for-byte intact, the pull
  source is marked degraded in the health surface with a remediation hint, no
  partial/empty week is written, and the weekly view (FRG-PULL-001) still renders
  from local metadata

#### Scenario: Source URL is fetched over the hardened external egress profile

- **WHEN** the configured `pull_source_url` resolves to a loopback, private, or
  link-local address
- **THEN** the fetch is refused per-hop by the external egress profile (FRG-SEC-001)
  rather than issued, and the refusal is surfaced as a degraded-source health
  condition — the pull source cannot be used to reach an internal host

#### Scenario: Untrusted / malformed source payload degrades, never crashes

- **WHEN** the source returns a malformed, oversized, or hostile JSON body
- **THEN** the parse is bounded (byte cap) and the run degrades to a source-outage
  outcome (stored week intact, source marked degraded) without raising, and no
  partially-parsed week is written

#### Scenario: Documented bad-date code skips only the affected week

- **WHEN** the source returns a 619 bad-date code for one of the requested weeks
- **THEN** that week is skipped with a logged warning while the other requested
  week is still fetched and stored, and the run is not treated as a full outage

#### Scenario: Enabled by default; disabling opts out completely

- **WHEN** a fresh install boots with no pull configuration, and separately when
  the operator sets `pull_enabled=false`
- **THEN** the fresh install's scheduled pull-refresh fetches from the default
  source (degrading gracefully if it is down), while the opted-out install issues
  no third-party traffic, its pull-refresh no-ops cleanly, and the weekly view
  still renders from local metadata
