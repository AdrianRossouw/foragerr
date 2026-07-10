# m4-logs-viewer — design

## Context

Owner-requested (2026-07-10, demo review): in-app visibility into what the
backend — especially acquisition — is doing. *arr prior art: Sonarr's
System → Log table with level filter and paging.

## Decisions

1. **In-memory ring buffer, not a DB table or file tailer.** A
   `collections.deque(maxlen=N)` behind a `logging.Handler` subclass
   attached to the root logger at startup. O(1) append, zero I/O in the
   logging hot path, bounded by construction (FRG-NFR-015), restart-clears
   (stdout stays the durable log). A DB table would put a write on every
   log record (the single-writer lock makes that a real cost) and need
   pruning; tailing the container's stdout isn't portable.
2. **Polling, not WS push.** A `log` WS family would make every buffered
   record a candidate push; WS-layer errors are themselves logged, so a
   degraded socket could feed itself (log → push → error → log). The Logs
   screen polls `GET /api/v1/log` on a short interval while **follow** is
   on and stops polling when off. No change to messages.py or the bridge.
3. **Handler sits AFTER the redaction filter.** The existing secret
   redaction (secrets self-register at config load, m1-foundation decision
   8) is a logging Filter; the ring-buffer handler is attached so records
   pass redaction before buffering — the API can never serve an unredacted
   secret that the stdout stream would have masked. Covered by a tagged
   test (secret in a log call → buffered record is masked).
4. **Level/logger filtering is server-side** on the paged read (the buffer
   holds up to `log_buffer_records`; shipping it whole to filter
   client-side defeats paging). Filters: minimum level (DEBUG..ERROR),
   logger dotted-prefix match.
5. **Audit-log position recorded, not implemented.** FRG-NFR-015 Notes
   state that a durable access/audit log (who did what, tamper-evident,
   retention policy) is a distinct requirement deferred to the auth
   milestone — with no principals before auth, an audit trail cannot
   attribute actions. This keeps the regulated-development trail honest
   without scope creep.

## Risks / Trade-offs

- [Info disclosure via `GET /api/v1/log`] → redaction-before-buffer
  (decision 3) + single-operator Tailscale posture (RISK-020 lineage);
  STRIDE + risk register updated in this change (FRG-PROC-006).
- [Buffer memory at max level] → bounded records × bounded formatted
  message length (records store the formatted string, capped); default
  2000 records ≈ low single-digit MB worst case.
- [Polling load while follow is on] → single cheap in-memory read per
  interval; interval ≥ 2s; polling stops when the tab/screen unmounts or
  follow is off.

## Migration Plan

Frontend + additive backend route/setting; no schema change; rollback =
revert.

## Open Questions

- None.
