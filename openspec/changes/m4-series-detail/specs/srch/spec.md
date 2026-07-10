# srch delta — m4-series-detail

## MODIFIED Requirements

### Requirement: FRG-SRCH-008 — Automatic search commands

The system SHALL provide automatic search as commands — single-issue search, missing-issues search, cutoff-unmet search — triggered after series add (per add options), after failed downloads, and on demand from UI/API, each running the decision engine over automatic-search-enabled indexers and auto-grabbing the best approved release per issue. `SeriesSearchCommand` SHALL accept a `monitored_only` flag (default true): the default walk covers the series' wanted issues exactly as before, while `monitored_only=false` — reachable only from an explicit operator action ("Search All") — widens the walk to every released, fileless issue of the series regardless of monitored state, via a dedicated selectable that leaves the wanted derivation untouched (FRG-SER-019).

- **Milestone**: M1 (Search All widening added in M4, m4-series-detail)
- **Source**: sonarr-arch §2.4 (ReleaseSearchService, command triggers); sonarr-arch §1.2 (post-add search); owner design handoff §2 (Search Monitored / Search All actions).
- **Notes**: Command-queue chassis is the SYS/backbone area; SRCH depends on it. No scheduler, RSS path, or chained add-flow search may set `monitored_only=false`.

#### Scenario: Search All widens to unmonitored missing issues on explicit request only

- **WHEN** a SeriesSearchCommand executes with `monitored_only=false`
- **THEN** the walk includes released, fileless issues the wanted set excludes for being unmonitored (and still excludes unreleased issues), while the default `monitored_only=true` walk and every scheduler/chained trigger remain scoped to the wanted set
