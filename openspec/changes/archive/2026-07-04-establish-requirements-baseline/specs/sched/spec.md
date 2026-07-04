# sched Spec Delta

## ADDED Requirements


### Requirement: FRG-SCHED-001 — command abstraction for background work

The system SHALL represent every unit of background work (refresh, scan, search, RSS sync, download tracking, post-processing, backup, housekeeping) as a typed command with a payload, priority, and lifecycle status (queued / started / completed / failed).

- **Milestone**: M1
- **Source**: sonarr-architecture.md §6.1 (CommandQueueManager) and §6.2 (asyncio equivalent: pydantic command models + dispatch by type).
- **Notes**: This is the chassis requirement — API `POST /command`, force-run, dedup, and history all hang off it. Fundamentals-first: allocate this before everything else in SCHED.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Every background action visible in the UI/API corresponds to a command record with a terminal status and duration; no background work executes outside the command path.

### Requirement: FRG-SCHED-002 — persisted command queue surviving restart

The system SHALL persist queued and started commands in the database, and on startup SHALL re-queue commands that were queued and mark commands that were started-but-unfinished as interrupted (re-queuing them where safe).

- **Milestone**: M1
- **Source**: sonarr-architecture.md §6.1 ("persisted (survives restart; orphans re-queued on startup)"); mylar-ddl.md §3.2 (restart loses queue order — weakness to fix).
- **Notes**: Explicit fix of Mylar's in-memory `queue.Queue` + DB smear. Idempotency/at-least-once semantics are stated in NFR crash-safe queues; this requirement owns the persistence mechanism.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Kill the process with commands queued; on restart the queued commands execute and the interrupted in-flight command is visible with an interrupted/failed status (and re-queued if idempotent).

### Requirement: FRG-SCHED-003 — command de-duplication

The system SHALL de-duplicate command submissions: pushing a command equal in type and payload to one already queued or started SHALL return the existing command instead of enqueuing a duplicate.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §6.1 ("de-duplicated (equal-bodied queued/started command returns the existing one)").
- **Notes**: Also subsumes Mylar's `PACK_ISSUEIDS_DONT_QUEUE` hack (mylar-ddl.md §1.7) at the command level; finer-grained "issue already covered by in-flight pack" logic stays in SRCH.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Submitting the same refresh-series command twice in quick succession yields one execution and both callers can track the same command id.

### Requirement: FRG-SCHED-004 — priority and exclusivity

The system SHALL execute commands in priority order and SHALL support marking command types as exclusive (at most one instance of that type or resource group running at a time).

- **Milestone**: M1
- **Source**: sonarr-architecture.md §6.1 (prioritized, exclusive/long-running flags); mylar-ddl.md §1.6 (DDL single-flight via `DDL_LOCK`); mylar-feature-surface.md §3 (SEARCHLOCK).
- **Notes**: Replaces Mylar's global locks (SEARCHLOCK, DDL_LOCK, IMPORTLOCK) with declarative exclusivity. Serialized-search politeness itself is an NFR/SRCH concern.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A high-priority download-tracking command queued behind bulk low-priority work runs next; two DDL download commands never run concurrently when the DDL group is exclusive.

### Requirement: FRG-SCHED-005 — worker pools per workload class

The system SHALL run a bounded set of asyncio workers partitioned by workload class — at minimum search, download (SAB tracking + DDL), and post-processing — such that saturation of one class does not starve the others, with blocking work (archive extraction, hashing, file I/O) offloaded to threads.

- **Milestone**: M1
- **Source**: mylar-feature-surface.md §8 ("Worker thread pools + queues: SEARCH_QUEUE, ..., PP_QUEUE, DDL_QUEUE"); sonarr-architecture.md §6.2 (N worker tasks, `asyncio.to_thread`).
- **Notes**: Pool sizes configurable with safe defaults (search 1 — indexer politeness; download 1 for DDL; PP 1-2). One command framework, multiple consumer groups — not five bespoke queues.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** With a long post-processing job running, a queued search command starts within its class's normal latency; the event loop remains responsive (health endpoint answers).

### Requirement: FRG-SCHED-006 — interval scheduler

The system SHALL run a scheduler loop (tick ≤ 60 s) that enqueues each recurring task's command when `last_execution + interval` has elapsed, with per-task intervals configurable and clamped to documented minimums, and last/next execution persisted.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §6.1 (30-second scheduler + TaskManager table) and §6.2 (hand-rolled loop over a `scheduled_tasks` table); mylar-feature-surface.md §7-8 (Scheduler section, interval min-clamping, APScheduler job table).
- **Notes**: Divergence from Mylar: hand-rolled loop per Sonarr's model rather than APScheduler, keeping schedule state inspectable in our own table. Initial task set (refresh, RSS/search, download tracking, folder scan, housekeeping, backup) is defined by the owning AREAs.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Setting RSS sync to its minimum interval produces enqueues at that cadence (observable in job history); configuring below the minimum clamps with a logged warning; schedules resume correctly after restart.

### Requirement: FRG-SCHED-007 — force-run of any scheduled task

The system SHALL allow any scheduled task to be triggered immediately via API/UI, returning a trackable command id, without disturbing the recurring schedule beyond updating last-execution on completion.

- **Milestone**: M1
- **Source**: mylar-feature-surface.md §8 ("force-run from UI"); sonarr-architecture.md §7.2 (command endpoint convention).
- **Notes**: The API surface shape (paths, resource fields) belongs to the API AREA; this requirement owns the capability.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** `POST /command {name: <task>}` starts the task now and returns 201 with a command resource whose status can be polled to completion.

### Requirement: FRG-SCHED-008 — persisted job history

The system SHALL persist an execution history for commands and scheduled tasks — including trigger (scheduled/manual/event), start/end time, duration, terminal status, and error message on failure — surviving restart and pruned by a retention policy.

- **Milestone**: M1
- **Source**: mylar-feature-surface.md §8 ("Job last-run/next-run persisted in the jobhistory table"); sonarr-architecture.md §6.1 (command status, LastExecution).
- **Notes**: Retention/pruning runs as the housekeeping command. This is also the audit trail the regulated-process demo wants — keep failure messages verbatim.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** After a restart, the UI/API still shows the previous runs of each scheduled task with status and duration; records older than the retention window are pruned by housekeeping.

### Requirement: FRG-SCHED-009 — in-process event bus

The system SHALL provide an in-process publish/subscribe event bus with typed events, where each handler's exception is isolated (logged, does not affect other handlers or the publisher) and handlers may be synchronous (inline) or fire-and-forget async.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §6.1 (EventAggregator, IHandle/IHandleAsync) and §6.2 (asyncio pub/sub equivalent).
- **Notes**: The glue for add→refresh→scan chains, grab→history, failed→blocklist→re-search. Events publish after DB commit (see DB transactional requirement).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A test event with one throwing handler and one recording handler results in the recording handler running and the publisher completing normally, with the error logged.

### Requirement: FRG-SCHED-010 — command status push to UI

The system SHALL broadcast command/queue status changes over a WebSocket channel (debounced) so the UI reflects background activity without polling.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §6.1 (CommandUpdatedEvent → SignalR) and §6.2/§7.4 (FastAPI WebSocket + React Query invalidation).
- **Notes**: M1 may poll `GET /command`; the WS channel lands in M2 with the broader UI push mechanism. Message schema ownership sits with the API AREA — dedup if API baselines WS push.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Triggering a force-run updates the UI task view to started and then completed without a page refresh, driven by WebSocket messages.

### Requirement: FRG-SCHED-011 — graceful queue drain on shutdown

On shutdown request, the system SHALL stop dequeuing new commands, allow in-flight commands a bounded grace period to finish or checkpoint, and persist final command states before exit.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §6.1 (orphan handling implies clean states); mylar-ddl.md §1.6 ('exit' sentinel shutdown); mylar-feature-surface.md §8.
- **Notes**: The queue half of DEP's graceful-shutdown requirement — DEP owns process/signal/HTTP behavior, SCHED owns queue semantics. Deliberately split; dedup by scope, not by merging.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** SIGTERM during active work exits within the grace period with the in-flight command recorded as completed or interrupted — never left as started after restart cleanup.
