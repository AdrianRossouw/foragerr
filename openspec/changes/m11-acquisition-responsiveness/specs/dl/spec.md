# dl — delta for m11-acquisition-responsiveness

## ADDED Requirements

### Requirement: FRG-DL-015 — Import-visibility stall escalation

The system SHALL remember consecutive import attempts that could not SEE
a completed download's files (a stall counter and first-stalled
timestamp on the tracked download, reset by any successful import or
genuinely new evidence — never by the routine completed-re-poll that
re-queues the attempt), and SHALL degrade
application health once a download's consecutive stalls pass a bounded
configurable threshold: one aggregated component carrying the stalled
count and the oldest stall, with remediation naming the path-visibility
class of fix (mount/path mapping between the download client and the
importer). The queue row's per-cycle honesty is unchanged — escalation
is additive memory, not a retry-behavior change.

A stall SHALL mean a genuine path-visibility failure — no output path,
a client path with no remote path mapping to translate it, or a path
under which not one file was seen — and SHALL NOT mean merely
"nothing was importable". A path the system can read that holds only
non-comic files is evidence the path IS visible, so it blocks per cycle
as usual and accrues no stall: the remediation this requirement carries
would be the wrong advice for it.

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

#### Scenario: A visible path holding nothing importable is not a stall

- **WHEN** a completed download's path is readable and holds files the
  importer does not import (an unrepaired archive set, notes, parity)
- **THEN** every cycle blocks with its per-cycle reason as usual, no
  stall accrues however long it repeats, and health does not degrade —
  the path is demonstrably visible, so this is a release problem

#### Scenario: An untranslatable client path escalates

- **WHEN** a completed download's client path has no remote path
  mapping to translate it, for more consecutive cycles than the
  threshold
- **THEN** health degrades with the same path-visibility remediation —
  the case the remediation names must be able to reach the threshold,
  even though it yields a blocked outcome rather than none

#### Scenario: The ping-pong never masks the count

- **WHEN** tracking re-queues a stalled download as import-pending
  between drain cycles (the designed retry-on-evidence loop)
- **THEN** the stall memory survives the state reset — the counter
  reflects consecutive no-file outcomes, not the row's instantaneous
  state
