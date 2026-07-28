# pp — delta for m11-source-import-trust

## ADDED Requirements

### Requirement: FRG-PP-021 — Provenance-authoritative series resolution

The system SHALL treat a grab-history series hint without an issue id
(the store-grab shape: the operator matched the entitlement to a series,
no specific issue was grabbed) as authoritative for the completed
download's resolution: the issue is derived from parse evidence within
that series (direct issue match, then the FRG-PP-022 ordinal fallback),
and resolution SHALL NOT fall through to unscoped filename-based series
matching. When no issue can be derived,
the file blocks with a reason that names the provenance series and states
that the issue could not be derived — never with a generic
"could not match series" reason. A grab hint carrying both series and
issue ids continues to short-circuit exactly as before (FRG-PP-003), and
an embedded issue-id tag retains its precedence above grab hints.

#### Scenario: Source-matched file imports despite unparseable series name

- **WHEN** a file named "Strangelands Issues #8.cbz" arrives from an
  entitlement the operator matched to the library series "Strangelands",
  and issue #8 exists in that series
- **THEN** the file imports to Strangelands #8 — the filler-polluted
  parsed series key is never consulted for series identity

#### Scenario: Provenance series wins over a parseable different series

- **WHEN** a file whose name parses cleanly to a different in-library
  series arrives from an entitlement matched to series S
- **THEN** resolution stays scoped to S (the operator's match outranks
  filename evidence, per the FRG-PP-004 confidence order); if the parsed
  issue number does not exist in S the file blocks with a reason naming S

#### Scenario: Underivable issue blocks honestly, series-scoped

- **WHEN** a source-matched file yields neither a matching issue number
  nor a usable ordinal for its provenance series
- **THEN** the file blocks with a reason naming the provenance series and
  the missing issue derivation, and manual import (FRG-PP-016) resolves
  it with an explicit issue override

### Requirement: FRG-PP-022 — Ordinal-fallback issue resolution under a known series

The system SHALL attempt ordinal-fallback issue resolution when the
target series of an import candidate is explicitly known (a provenance
series per FRG-PP-021, or a series-scoped rescan) and the aggregated
evidence yields no issue but yields an ordinal volume (`Vol. N` and
equivalents per FRG-IMP-012): issue N is tried against that series' real
issue index using the standard issue-equality match. The fallback SHALL only produce a mapping when
issue N exists in the known series; a miss leaves the file blocked. The
fallback SHALL NOT fire when the evidence contains an actual issue number
(a present issue that misses the index blocks — the ordinal never
overrides stronger evidence), and it SHALL NOT alter parser semantics:
`volume_ordinal` and `issue` remain distinct parse fields.

#### Scenario: Mislabeled single lands via its ordinal

- **WHEN** "SPAWN Vol. 243.cbz" arrives from an entitlement matched to a
  Spawn series that contains issue #243
- **THEN** the file imports as issue #243

#### Scenario: True trade lands in its collected-edition series

- **WHEN** "Saga Vol. 4.cbz" arrives with its target series explicitly
  set to the Saga collected-edition volume whose issue list contains #4
- **THEN** the file imports as that series' issue #4

#### Scenario: Ordinal miss stays blocked

- **WHEN** a file parsing to `Vol. 9` with no issue number targets a
  known series whose issue index contains no issue 9
- **THEN** the file blocks (no fabricated issue), with the
  FRG-PP-021-style series-scoped reason

#### Scenario: Present issue evidence is never overridden by the ordinal

- **WHEN** a file parses to both an issue number and an ordinal volume,
  and the issue number does not exist in the known series
- **THEN** the file blocks; the ordinal is not consulted

## MODIFIED Requirements

### Requirement: FRG-PP-016 — Manual import resolution

The system SHALL provide a manual import view listing candidate files (from an import-blocked download or an arbitrary folder) with their would-be decisions and rejection reasons, allowing the user to override series, issue, and format per file and then execute those files through the shared import pipeline. Executing a download-scoped manual import SHALL apply the resulting terminal state to the download's tracked queue row through the same state-application path as the automatic drain (emitting the same queue events), so a resolved download never lingers as import-blocked in the queue.

- **Milestone**: M2
- **Source**: SA §5.5 (ManualImportService — "the escape hatch for every mapping failure"), §4.5 (ImportBlocked → ManualInteractionRequiredEvent); MFS §4 (manual PP of arbitrary folder).
- **Notes**: The resolution path the M1 import-blocked state points at. Executes through the SAME `import_candidate` (one `aggregate → decide → execute`); a `ManualImportSource` produces neutral `ImportCandidate`s (reusing `CompletedDownloadSource.gather` for the blocked-download entry point, an unscoped folder walk for the ad-hoc entry point); overrides enter as the top-priority reconciliation layer and bypass ONLY the series/issue mapping specs. Terminal-state aggregation reuses the drain's policy (extracted, not duplicated) so both flows compute identical states for identical outcomes; source-download entitlement mirroring on this path is governed by FRG-SRC-006.

#### Scenario: Blocked download resolved by override through the shared pipeline

- **WHEN** an `import_blocked` download whose file failed automatic mapping is listed via manual import, and the user submits a series/issue override for that file
- **THEN** the override pins `(series_id, issue_id)` at the reconciliation seam, `import_candidate` runs the full spec set over the pinned evaluation, the file imports via `execute`, and the same `imported` history event and `issue_files` row are written as an automatic import — with no separate manual code path.

#### Scenario: Arbitrary folder of unmatched files

- **WHEN** manual import is opened on an arbitrary folder of archives that carry no grab record
- **THEN** each file is walked with the same bounded `iter_archive_files` intake, aggregated and decided so its would-be verdict and reasons show, and a per-file override drives it through `import_candidate` to the correct issue.

#### Scenario: Override bypasses mapping but NOT the safety specs

- **WHEN** a user overrides series/issue for a file whose archive is corrupt (or which is below the junk-size floor, or whose destination volume lacks free space)
- **THEN** the mapping specs are satisfied by the override but `ArchiveValidSpec` / `JunkFilterSpec` / `FreeSpaceSpec` still evaluate and reject, so the file is NOT force-imported and its verdict lists the real blocking reason.

#### Scenario: Override to a non-existent entity is not trusted

- **WHEN** a submitted override names a `series_id`/`issue_id` that does not exist, or an issue that does not belong to the chosen series
- **THEN** the override is dropped rather than fabricating a mapping, the candidate falls back to the normal heuristic, and if it still cannot resolve it stays blocked with a visible reason — never imported to a phantom entity.

#### Scenario: Failed manual candidate stays listed, not lost

- **WHEN** a manually-submitted file fails during execution (e.g. an IO error placing the file)
- **THEN** it is parked BLOCKED with a visible reason (never FAILED-blocklisted for an environmental error, never auto-deleted), and it remains available in the manual-import listing for another attempt.

#### Scenario: Download-scoped execute updates the tracked queue row

- **WHEN** a download-scoped manual import executes and its files all import successfully
- **THEN** the download's tracked row transitions to the imported terminal state through the same state-application path as the automatic drain (same queue event emitted), and the queue no longer lists the download as import-blocked

#### Scenario: Partially resolved download keeps an honest queue state

- **WHEN** a download-scoped manual import executes and at least one of the download's files remains blocked or failed
- **THEN** the tracked row's state reflects that outcome under the same aggregation policy the automatic drain applies to a mixed result — never a silent stale `import_blocked` from before the attempt
