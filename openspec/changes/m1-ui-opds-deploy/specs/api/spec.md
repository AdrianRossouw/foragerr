## MODIFIED Requirements

### Requirement: FRG-API-010 — WebSocket resource-change push

The backend SHALL expose a WebSocket endpoint broadcasting resource-change messages (`{name, action, resource}`) for at least queue, command, series, and issue-file changes, debounced (~100 ms), as the SignalR equivalent driving live UI updates.

- **Milestone**: M1
- **Source**: sonarr-architecture.md §6.1 UI push (ModelEvent → SignalR), §6.2 asyncio equivalent (FastAPI WebSocket, debounced broadcast).
- **Notes**: M1 may scope broadcast coverage to queue+command (what the slice's "queue tracking" needs); remaining resources by M2. Auth on the WS endpoint is AUTH/M3.

#### Scenario: Resource change is pushed without polling

- **WHEN** a client is connected to `/api/v1/ws` and a release is grabbed
- **THEN** the client receives a `{name, action, resource}` JSON message for the queue change without issuing any HTTP poll, and a command status change produces a corresponding command message

#### Scenario: Events are batched and debounced per (name, action)

- **WHEN** the event bus emits a burst of changes for the same (name, action) within ~100 ms
- **THEN** the subscriber coalesces them and broadcasts at most one batched message for that (name, action) after the debounce window rather than one message per underlying event

#### Scenario: Slow client is dropped and never blocks the bus

- **WHEN** one connected client stops draining its socket while events continue to flow
- **THEN** that socket's per-socket send queue fills, the slow client is dropped/closed, and other clients and the event bus continue delivering without stalling

#### Scenario: Reconnecting client resumes receiving

- **WHEN** a client disconnects and later reconnects to `/api/v1/ws`
- **THEN** it begins receiving subsequent resource-change broadcasts again; the endpoint enforces no auth in M1 (Origin validation is deferred to FRG-SEC-005/M3, recorded as a residual risk)
