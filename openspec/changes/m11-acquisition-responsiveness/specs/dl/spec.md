# dl — delta for m11-acquisition-responsiveness

## ADDED Requirements

### Requirement: FRG-DL-015 — Import-visibility stall escalation

The system SHALL remember consecutive import attempts that found no
importable files under a completed download's path (a stall counter and
first-stalled timestamp on the tracked download, reset by any
successful import or genuinely new evidence — never by the routine
completed-re-poll that re-queues the attempt), and SHALL degrade
application health once a download's consecutive stalls pass a bounded
configurable threshold: one aggregated component carrying the stalled
count and the oldest stall, with remediation naming the path-visibility
class of fix (mount/path mapping between the download client and the
importer). The queue row's per-cycle honesty is unchanged — escalation
is additive memory, not a retry-behavior change.

#### Scenario: The silent stall becomes a health warning

- **WHEN** a download the client reports as completed produces
  no-importable-files outcomes for more consecutive drain cycles than
  the threshold
- **THEN** health degrades with the stalled download counted, the
  oldest stall shown, and mount/path guidance — while the queue row
  continues to show its per-cycle state

#### Scenario: Real progress clears the memory

- **WHEN** a previously stalling download's files become visible and an
  import succeeds
- **THEN** the stall memory resets, and health clears once no download
  is past the threshold

#### Scenario: The ping-pong never masks the count

- **WHEN** tracking re-queues a stalled download as import-pending
  between drain cycles (the designed retry-on-evidence loop)
- **THEN** the stall memory survives the state reset — the counter
  reflects consecutive no-file outcomes, not the row's instantaneous
  state
