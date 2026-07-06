# sched — delta for m2-daily-surfaces

## MODIFIED Requirements

### Requirement: FRG-SCHED-010 — command status push to UI

The system SHALL broadcast command/queue status changes over a WebSocket channel (debounced) so the UI reflects background activity without polling, covering every lifecycle transition a client can observe: queued, started, and the terminal outcome.

- **Milestone**: M2
- **Source**: sonarr-architecture.md §6.1 (CommandUpdatedEvent → SignalR) and §6.2/§7.4 (FastAPI WebSocket + React Query invalidation).
- **Notes**: Largely landed with the M1 WS bridge (queued + terminal pushes, 100 ms coalescing, FRG-API-010); this change closes the one gap — the `started` claim emitted no event — and pins the full lifecycle with a tagged test. Message schema ownership sits with the API AREA.

#### Scenario: Force-run shows started then completed without refresh

- **WHEN** a command is enqueued and a WS client is connected
- **THEN** the client receives command-updated pushes for queued, for the started claim, and for the terminal outcome (coalesced within the debounce window but never skipping the terminal state), so a UI reflects "running" without polling
