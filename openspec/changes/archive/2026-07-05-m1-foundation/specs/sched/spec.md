## MODIFIED Requirements

### Requirement: FRG-SCHED-001 — command abstraction for background work

The system SHALL represent every unit of background work (refresh, scan, search, RSS sync, download tracking, post-processing, backup, housekeeping) as a typed command with a payload, priority, and lifecycle status (queued / started / completed / failed).

- **Milestone**: M1
- **Source**: sonarr-architecture.md §6.1 (CommandQueueManager) and §6.2 (asyncio equivalent: pydantic command models + dispatch by type).
- **Notes**: This is the chassis requirement — API `POST /command`, force-run, dedup, and history all hang off it. Fundamentals-first: allocate this before everything else in SCHED.

#### Scenario: Command lifecycle recorded from enqueue to terminal status

- **WHEN** a command is enqueued and its handler runs to completion
- **THEN** a row exists in the `commands` table that transitions `queued` → `started` → `completed`, with enqueue/start/finish timestamps set and a duration derivable from them, and the row carries the command's name, priority, and payload as persisted JSON

#### Scenario: Handler failure yields a failed command with the error preserved

- **WHEN** a command's handler raises an exception
- **THEN** the command reaches terminal status `failed` with the error message recorded on the row, and the worker that ran it continues processing subsequent commands normally

#### Scenario: Malformed command payload is rejected at enqueue

- **WHEN** a command is submitted whose name is unknown or whose payload does not validate against that command's Pydantic model
- **THEN** the enqueue is rejected with a validation error and no row is created in the `commands` table

#### Scenario: No background work executes outside the command path

- **WHEN** any built-in background action (refresh, scan, search, RSS sync, download tracking, post-processing, backup, housekeeping) is triggered by schedule or by API
- **THEN** a corresponding command record with a terminal status and duration is observable; no background work executes outside the command path

### Requirement: FRG-SCHED-002 — persisted command queue surviving restart

The system SHALL persist queued and started commands in the database, and on startup SHALL re-queue commands that were queued and mark commands that were started-but-unfinished as interrupted (re-queuing them where safe).

- **Milestone**: M1
- **Source**: sonarr-architecture.md §6.1 ("persisted (survives restart; orphans re-queued on startup)"); mylar-ddl.md §3.2 (restart loses queue order — weakness to fix).
- **Notes**: Explicit fix of Mylar's in-memory `queue.Queue` + DB smear. Idempotency/at-least-once semantics are stated in NFR crash-safe queues; this requirement owns the persistence mechanism.

#### Scenario: Queued commands survive an unclean restart

- **WHEN** the process is killed (no graceful shutdown) while commands sit in status `queued`
- **THEN** after restart those commands are still present in the `commands` table as `queued` and are subsequently executed to a terminal status without re-submission

#### Scenario: Orphaned started command is re-queued on startup

- **WHEN** the process is killed while a command is in status `started`, and the system starts up again
- **THEN** startup recovery returns the orphaned row to the queue and the command runs again to completion, and the effect of the re-run is the same as a single run (the work is idempotent — no duplicated side effects observable)

#### Scenario: Recovery is visible in the command record

- **WHEN** an interrupted command has been recovered and completed after restart
- **THEN** the command's history shows the interruption and the successful re-execution (it is never left indefinitely in `started` from the previous process lifetime)

### Requirement: FRG-SCHED-003 — command de-duplication

The system SHALL de-duplicate command submissions: pushing a command equal in type and payload to one already queued or started SHALL return the existing command instead of enqueuing a duplicate.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §6.1 ("de-duplicated (equal-bodied queued/started command returns the existing one)").
- **Notes**: Also subsumes Mylar's `PACK_ISSUEIDS_DONT_QUEUE` hack (mylar-ddl.md §1.7) at the command level; finer-grained "issue already covered by in-flight pack" logic stays in SRCH.

#### Scenario: Duplicate enqueue returns the existing command

- **WHEN** the same command (same name, payload equal by payload-hash) is submitted twice while the first is still `queued` or `started`
- **THEN** the second submission returns the first command's id and no second row is created in the `commands` table, and both callers polling that id observe the single execution reach one terminal status

#### Scenario: Different payloads are not de-duplicated

- **WHEN** two commands of the same name but different payloads are submitted
- **THEN** two distinct rows are created and both execute

#### Scenario: Terminal commands do not block re-submission

- **WHEN** a command has reached a terminal status (completed, failed, or cancelled) and an equal-bodied command is submitted afterwards
- **THEN** a new command row is created and executed — dedup considers only `queued` and `started` rows

### Requirement: FRG-SCHED-004 — priority and exclusivity

The system SHALL execute commands in priority order and SHALL support marking command types as exclusive (at most one instance of that type or resource group running at a time).

- **Milestone**: M1
- **Source**: sonarr-architecture.md §6.1 (prioritized, exclusive/long-running flags); mylar-ddl.md §1.6 (DDL single-flight via `DDL_LOCK`); mylar-feature-surface.md §3 (SEARCHLOCK).
- **Notes**: Replaces Mylar's global locks (SEARCHLOCK, DDL_LOCK, IMPORTLOCK) with declarative exclusivity. Serialized-search politeness itself is an NFR/SRCH concern.

#### Scenario: Higher-priority command jumps the queue

- **WHEN** several low-priority commands are queued for a workload class and a high-priority command of the same class is then enqueued
- **THEN** the high-priority command is claimed by the next free worker before the remaining low-priority commands

#### Scenario: Exclusivity group serializes execution

- **WHEN** two commands belonging to the same exclusivity group are eligible to run and worker capacity would allow both concurrently
- **THEN** they run strictly one after the other — at no observable point are both in status `started` with their handlers executing simultaneously

#### Scenario: Exclusivity does not block unrelated work

- **WHEN** a long-running command holds its exclusivity group's lock
- **THEN** queued commands in other groups (or with no group) are still claimed and executed by available workers

### Requirement: FRG-SCHED-005 — worker pools per workload class

The system SHALL run a bounded set of asyncio workers partitioned by workload class — at minimum search, download (SAB tracking + DDL), and post-processing — such that saturation of one class does not starve the others, with blocking work (archive extraction, hashing, file I/O) offloaded to threads.

- **Milestone**: M1
- **Source**: mylar-feature-surface.md §8 ("Worker thread pools + queues: SEARCH_QUEUE, ..., PP_QUEUE, DDL_QUEUE"); sonarr-architecture.md §6.2 (N worker tasks, `asyncio.to_thread`).
- **Notes**: Pool sizes configurable with safe defaults (search 1 — indexer politeness; download 1 for DDL; PP 1-2). One command framework, multiple consumer groups — not five bespoke queues.

#### Scenario: Default pool sizes cap per-class concurrency

- **WHEN** the system starts with default configuration and many commands of every class are queued
- **THEN** at most 1 search, 1 download, 1 post-processing, and 2 default-class commands are in `started` at any one time

#### Scenario: Saturation of one class does not starve another

- **WHEN** the post-processing pool is fully occupied by a long-running job and a search command is enqueued
- **THEN** the search command starts within its own class's normal latency, unaffected by the busy post-processing pool

#### Scenario: Blocking work keeps the event loop responsive

- **WHEN** a command whose handler performs blocking work (e.g. archive extraction or hashing, offloaded via `asyncio.to_thread`) is running
- **THEN** concurrent async operations on the event loop (e.g. the health endpoint) continue to respond within normal latency for the duration of the blocking work

### Requirement: FRG-SCHED-006 — interval scheduler

The system SHALL run a scheduler loop (tick ≤ 60 s) that enqueues each recurring task's command when `last_execution + interval` has elapsed, with per-task intervals configurable and clamped to documented minimums, and last/next execution persisted.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §6.1 (30-second scheduler + TaskManager table) and §6.2 (hand-rolled loop over a `scheduled_tasks` table); mylar-feature-surface.md §7-8 (Scheduler section, interval min-clamping, APScheduler job table).
- **Notes**: Divergence from Mylar: hand-rolled loop per Sonarr's model rather than APScheduler, keeping schedule state inspectable in our own table. Initial task set (refresh, RSS/search, download tracking, folder scan, housekeeping, backup) is defined by the owning AREAs.

#### Scenario: Due task is enqueued within one tick

- **WHEN** a task in the `scheduled_tasks` table has `last_run + interval` in the past
- **THEN** the scheduler loop enqueues that task's command within one tick (≤ 60 s) and updates the task's `last_run`, so job history shows enqueues at the configured cadence

#### Scenario: Interval below the documented minimum is clamped

- **WHEN** a task's interval is configured below its documented minimum
- **THEN** the effective interval used by the scheduler is the minimum, and a warning is logged recording the clamp

#### Scenario: Schedule state survives restart

- **WHEN** the process restarts partway through a task's interval
- **THEN** the persisted `last_run` is honoured — the task next fires at `last_run + interval`, neither firing immediately on every startup nor resetting its timer

#### Scenario: A not-yet-due task is not enqueued

- **WHEN** the scheduler ticks while a task's `last_run + interval` has not yet elapsed
- **THEN** no command is enqueued for that task on that tick

### Requirement: FRG-SCHED-007 — force-run of any scheduled task

The system SHALL allow any scheduled task to be triggered immediately via API/UI, returning a trackable command id, without disturbing the recurring schedule beyond updating last-execution on completion.

- **Milestone**: M1
- **Source**: mylar-feature-surface.md §8 ("force-run from UI"); sonarr-architecture.md §7.2 (command endpoint convention).
- **Notes**: The API surface shape (paths, resource fields) belongs to the API AREA; this requirement owns the capability.

#### Scenario: Force-run enqueues immediately and is trackable

- **WHEN** `POST /command {name: <task>}` is called for a scheduled task that is not currently due
- **THEN** the response is 201 with a command resource whose id can be polled through `queued` / `started` to a terminal status, and the command begins without waiting for the schedule

#### Scenario: Force-run resets the recurring timer

- **WHEN** a scheduled task is force-run to completion
- **THEN** the task's `last_run` is updated to the force-run execution, so the next scheduled fire occurs one full interval after the force-run rather than on the old cadence

#### Scenario: Force-run of an already-running task de-duplicates

- **WHEN** a force-run is requested for a task whose equal-bodied command is already `queued` or `started`
- **THEN** the existing command's id is returned and no duplicate execution occurs

### Requirement: FRG-SCHED-008 — persisted job history

The system SHALL persist an execution history for commands and scheduled tasks — including trigger (scheduled/manual/event), start/end time, duration, terminal status, and error message on failure — surviving restart and pruned by a retention policy.

- **Milestone**: M1
- **Source**: mylar-feature-surface.md §8 ("Job last-run/next-run persisted in the jobhistory table"); sonarr-architecture.md §6.1 (command status, LastExecution).
- **Notes**: Retention/pruning runs as the housekeeping command. This is also the audit trail the regulated-process demo wants — keep failure messages verbatim.

#### Scenario: Every execution writes a history row

- **WHEN** any command executes — whether triggered by the scheduler, a manual force-run, or an event
- **THEN** a `job_history` row is written recording the trigger, start and finish times, outcome, and (on failure) the verbatim error message

#### Scenario: History survives restart

- **WHEN** the process restarts after several commands have run
- **THEN** the API still returns the previous runs of each scheduled task with their status and duration, unchanged by the restart

#### Scenario: Housekeeping prunes history by retention

- **WHEN** the housekeeping command runs while `job_history` contains rows older than the retention window and rows within it
- **THEN** only the rows older than the retention window are deleted; recent rows are untouched

### Requirement: FRG-SCHED-009 — in-process event bus

The system SHALL provide an in-process publish/subscribe event bus with typed events, where each handler's exception is isolated (logged, does not affect other handlers or the publisher) and handlers may be synchronous (inline) or fire-and-forget async.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §6.1 (EventAggregator, IHandle/IHandleAsync) and §6.2 (asyncio pub/sub equivalent).
- **Notes**: The glue for add→refresh→scan chains, grab→history, failed→blocklist→re-search. Events publish after DB commit (see DB transactional requirement).

#### Scenario: Subscribers receive published events by type

- **WHEN** two handlers subscribe to an event type and an event of that type is published
- **THEN** both handlers are invoked with the event; a handler subscribed to a different event type is not invoked

#### Scenario: A throwing handler does not affect other handlers or the publisher

- **WHEN** an event is published to one handler that raises and one that records
- **THEN** the recording handler runs to completion, the publisher's `publish` call completes normally, and the throwing handler's exception is logged

#### Scenario: Events tied to a DB write publish only after commit

- **WHEN** an event is published as part of an operation whose database transaction is rolled back
- **THEN** no subscriber observes the event; subscribers observe events for that operation only after its transaction has committed

### Requirement: FRG-SCHED-011 — graceful queue drain on shutdown

On shutdown request, the system SHALL stop dequeuing new commands, allow in-flight commands a bounded grace period to finish or checkpoint, and persist final command states before exit.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §6.1 (orphan handling implies clean states); mylar-ddl.md §1.6 ('exit' sentinel shutdown); mylar-feature-surface.md §8.
- **Notes**: The queue half of DEP's graceful-shutdown requirement — DEP owns process/signal/HTTP behavior, SCHED owns queue semantics. Deliberately split; dedup by scope, not by merging.

#### Scenario: SIGTERM stops new claims and lets in-flight work finish

- **WHEN** SIGTERM arrives while one command is in-flight and others are queued
- **THEN** no queued command is claimed after the signal, the in-flight command finishes within the grace period and is persisted with a terminal status, and the process exits cleanly

#### Scenario: Queued commands persist untouched across a graceful shutdown

- **WHEN** the process shuts down gracefully with commands still queued
- **THEN** after restart those commands remain in status `queued` in the database and are executed normally — startup recovery finds no orphaned `started` rows from the previous run

#### Scenario: Grace period is bounded and configurable

- **WHEN** an in-flight command does not finish within the configured grace period (default under 30 s)
- **THEN** the process still exits within the bound, and the command's row is left in a state that startup recovery re-queues rather than remaining silently `started`
