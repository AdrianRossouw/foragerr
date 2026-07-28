# sched — delta for m11-acquisition-responsiveness

## ADDED Requirements

### Requirement: FRG-SCHED-012 — First-indexer sweep and next-search visibility

The system SHALL enqueue one bounded backlog-search run when the first
enabled indexer is configured on a deployment that previously had none
— the fresh-install order where series arrive before indexers gets its
first sweep from the indexer side instead of waiting for the scheduled
tick. That sweep SHALL happen at most once per installation, recorded
by a persisted one-shot marker claimed atomically rather than inferred
from live indexer counts: indexer churn (deleting and re-adding, or
disabling and re-enabling) never re-fires it, and simultaneous first
configurations resolve to exactly one sweep rather than none. The system
SHALL surface the next scheduled automatic search contextually where
wanted items are shown, from the existing scheduled-task next-run data
— never a second scheduler.

#### Scenario: The first enabled indexer triggers one sweep

- **WHEN** an indexer is created (or enabled) on a deployment whose
  enabled-indexer count was zero, with monitored series already present
- **THEN** one backlog-search command is enqueued (normal dedup and
  politeness apply), and creating further indexers triggers nothing

#### Scenario: Indexer churn never re-fires the sweep

- **WHEN** the only indexer is deleted and another created, or an
  indexer is disabled and re-enabled, after the sweep has already run
- **THEN** no further sweep is enqueued — the scheduled tick owns that
  ground from then on

#### Scenario: Wanted shows when the machine will look next

- **WHEN** the operator views wanted items while the backlog search is
  scheduled
- **THEN** the surface shows the next automatic search time from the
  scheduler's own next-run data
