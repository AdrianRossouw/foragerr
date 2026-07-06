## MODIFIED Requirements

### Requirement: FRG-IMP-024 — Embedded metadata read during import

During library import, the system SHALL read embedded ComicInfo.xml metadata (and embedded ComicVine issue IDs) from archives where present and SHALL prefer a verified embedded ID over filename-parse results when matching files to series/issues.

- **Milestone**: M2
- **Source**: MFS §4 Library import (embedded ComicInfo read, direct add-by-ID); MFS capability map IMP.
- **Notes**: Read-side only. The embedded read runs in the `build_evaluation` stage (which already does archive I/O), bounded by the shared `inspect_archive` limits with no extraction; parsing routes through the single hardened XML site (FRG-SEC-002). A verified embedded CV id (`cv_issue_id` namespace) becomes a new highest-confidence reconciliation input, seated above the filename heuristic but below an explicit manual override.

#### Scenario: Verified embedded id beats a misleading filename

- **WHEN** a cbz carries a ComicInfo.xml whose ComicVine issue id resolves to an existing library issue, under a filename that parses to a different/looser match
- **THEN** the verified embedded id resolves `(series_id, issue_id)` directly ahead of the filename parse and the file imports to that issue; provenance records the id came from ComicInfo.

#### Scenario: Conflicting or unresolvable id is not silently trusted

- **WHEN** the embedded id does not resolve to any library issue, or resolves to an issue conflicting with a strong filename series match (or, in a scoped context, to another series)
- **THEN** it does NOT silently win — the candidate resolves by the normal heuristic and the conflict is recorded so it surfaces as a review/blocked item rather than a silent mis-file.

#### Scenario: Malformed or hostile ComicInfo never crashes the pipeline

- **WHEN** the ComicInfo.xml is not well-formed, or carries a DTD/entity/external-entity payload
- **THEN** the hardened parser rejects it and the read returns empty/partial embedded metadata with a parse-degraded note; the candidate continues on filename evidence and never raises out of the pipeline.

#### Scenario: Oversized ComicInfo member skipped under the caps

- **WHEN** the ComicInfo member declares a size over the per-member ComicInfo cap
- **THEN** it is skipped before any read (no unbounded load), yielding no embedded metadata, and the file imports on its remaining evidence.

#### Scenario: Read stays within inspection limits, no extraction

- **WHEN** embedded metadata is read from an archive
- **THEN** only the vetted central-directory member list is used, the single root-level `ComicInfo.xml` is read into memory bounded by its declared size, and nothing is extracted to disk — the same `inspect_archive` limits that gate import validity gate the read.
