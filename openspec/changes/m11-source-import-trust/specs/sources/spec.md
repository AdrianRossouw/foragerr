# sources — delta for m11-source-import-trust

## ADDED Requirements

### Requirement: FRG-SRC-008 — Review-proposal freshness after library mutations

The system SHALL keep entitlement review proposals actionable as the
library changes underneath them. The add action on an entitlement whose
proposed (or explicitly supplied) ComicVine volume already exists in the
library SHALL degrade to matching the entitlement to that existing series
instead of failing. When an add action successfully creates a series, the
system SHALL, before the action returns, re-resolve the proposals of
sibling entitlements still in review whose proposal targeted the same
ComicVine volume, converting them to match proposals against the new
series so their next action succeeds on the first click. The
re-resolution need not share one database transaction with the series
add (which commits in its own steps), but every intermediate state SHALL
be self-healing: a sibling acted on before or without the sweep degrades
to the equivalent match rather than erroring.

#### Scenario: Add on an in-library volume degrades to match

- **WHEN** the operator triggers add on an entitlement whose proposed
  ComicVine volume is already present as a library series
- **THEN** the entitlement is matched to that series (identical outcome
  to the match action, including grab queueing rules), and no error is
  returned

#### Scenario: Siblings re-resolve after a successful add

- **WHEN** an add action creates a library series from ComicVine volume V
  while other entitlements in review carry proposals targeting V
- **THEN** those siblings' proposals become match proposals pointing at
  the new series, and each sibling's next single action matches it
  without an error

#### Scenario: Operator decisions are never overwritten

- **WHEN** the sibling re-resolution sweep runs
- **THEN** only entitlements still in the `new` review state are touched
  — matched and ignored entitlements are left exactly as the operator
  set them

### Requirement: FRG-SRC-009 — Failed source-download visibility and retry

The system SHALL provide an explicit retry action for an entitlement
whose download has failed, exposed as an API action and as an affordance
on the failed review row, which clears the recorded failure and re-queues
the grab through the standard grab path. The system SHALL surface failed
source downloads in application health: a source with one or more
entitlements in a failed download state degrades to a warning that
carries the failed count and remediation pointing at the source's review
screen — aggregated per source, never one health entry per entitlement.

#### Scenario: Retry re-queues a failed download

- **WHEN** the operator triggers retry on an entitlement whose download
  state is failed
- **THEN** the failure reason is cleared, the grab is re-queued through
  the standard grab task, and the download state reflects the new attempt

#### Scenario: Retry is only valid for failed downloads

- **WHEN** retry is triggered on an entitlement whose download state is
  not failed
- **THEN** the action is rejected with a conflict error and no state
  changes

#### Scenario: Failed downloads degrade health, aggregated per source

- **WHEN** a source has N > 0 entitlements whose download state is failed
- **THEN** the health surface reports one degraded component for that
  source carrying the failed count and a remediation hint, and the
  warning clears when no failed downloads remain

## MODIFIED Requirements

### Requirement: FRG-SRC-006 — entitlement download and import handoff

The system SHALL download an accepted entitlement by fetching a fresh signed URL from
the order API at grab time, streaming over HTTPS to the existing download staging
area with bounded size and timeout (FRG-NFR-006), restricting destinations to the
Humble CDN host allowlist, verifying the response against the API-provided md5, and
handing the verified file to the existing import pipeline as a normal completed
download. Verification or download failures SHALL surface on the entitlement's
download state with the failure reason and a retry action (FRG-SRC-009); grab
failures deliberately do NOT enter the usenet failed-download loop, whose fused
blocklist-plus-automatic-indexer-re-search semantics are meaningless for
account-owned store content (there is nothing to blocklist or re-search).
Every import path SHALL mirror the import outcome onto the entitlement's download
state and run the FRG-SRC-007 owned-via-edition reconciliation: the automatic drain
and a manual import of a source download (FRG-PP-016) produce the same entitlement
transitions — a manually resolved source download never leaves the entitlement
stuck in a blocked or failed state.

#### Scenario: Happy path to library

- **WHEN** the operator accepts a matched entitlement
- **THEN** the file is fetched from a freshly obtained signed URL, md5-verified, imported by the standard pipeline, and the entitlement shows `matched` with its issues owned

#### Scenario: Checksum mismatch quarantined

- **WHEN** a downloaded file's md5 does not match the API metadata
- **THEN** the file is not imported (quarantined aside), the failure is recorded on the entitlement's download state with its reason, and retry is available (FRG-SRC-009)

#### Scenario: Egress confinement

- **WHEN** the order API returns a download URL whose host is outside the Humble CDN allowlist or scheme is not HTTPS
- **THEN** the download is refused and logged, and the entitlement shows a failure state

#### Scenario: Manual import mirrors the entitlement like the drain

- **WHEN** a blocked source download is resolved through manual import
  (FRG-PP-016) and its file imports successfully
- **THEN** the entitlement's download state transitions to imported in
  the same write transaction, owned-via-edition reconciliation
  (FRG-SRC-007) runs exactly as it would on the automatic drain path,
  and no stale blocked state remains on the entitlement or its queue row
