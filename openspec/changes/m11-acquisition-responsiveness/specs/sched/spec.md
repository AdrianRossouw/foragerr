# sched — delta for m11-acquisition-responsiveness

## ADDED Requirements

### Requirement: FRG-SCHED-012 — First-indexer sweep and next-search visibility

The system SHALL enqueue one bounded backlog-search run when the first
enabled indexer is configured on a deployment that previously had none
(the enabled count transitions zero to one) — the fresh-install order
where series arrive before indexers gets its first sweep from the
indexer side instead of waiting for the scheduled tick. The system
SHALL surface the next scheduled automatic search contextually where
wanted items are shown, from the existing scheduled-task next-run data
— never a second scheduler.

#### Scenario: The first enabled indexer triggers one sweep

- **WHEN** an indexer is created (or enabled) on a deployment whose
  enabled-indexer count was zero, with monitored series already present
- **THEN** one backlog-search command is enqueued (normal dedup and
  politeness apply), and creating further indexers triggers nothing

#### Scenario: Wanted shows when the machine will look next

- **WHEN** the operator views wanted items while the backlog search is
  scheduled
- **THEN** the surface shows the next automatic search time from the
  scheduler's own next-run data
