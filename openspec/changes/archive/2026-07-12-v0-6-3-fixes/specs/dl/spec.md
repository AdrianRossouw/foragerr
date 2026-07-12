# dl Spec Delta

## MODIFIED Requirements

### Requirement: FRG-DL-003 — SABnzbd add via file upload

To grab a usenet release, the system SHALL itself fetch the NZB bytes from the indexer (with retry), validate them, and POST them to SABnzbd with `mode=addfile`, a dedicated configurable category (default "comics"), and a configurable priority, treating an empty `nzo_id` response as a grab failure.

- **Milestone**: M1
- **Source**: sonarr-arch §4.2 (UsenetClientBase.Download, mode=addfile)
- **Notes**: Deliberate divergence from Mylar's add-by-URL flow (SAB pulling
  the NZB back from Mylar's API with a one-time download key) — that scheme
  adds an extra auth surface and a callback dependency; recommend permanent
  exclusion (mylar-fs DL). Server-side fetch keeps indexer credentials off SAB
  and allows NZB validation. Amended by v0-6-3-fixes (2026-07-12): validation
  parses via the NZB-specific hardened entry point (FRG-SEC-002 carve-out) —
  the previous blanket-DOCTYPE-ban parse rejected every spec-conformant NZB.

#### Scenario: Server-side NZB fetch through the indexer back-off ladder

- **WHEN** a usenet release is grabbed
- **THEN** foragerr fetches the NZB bytes server-side from the indexer via the external egress profile, subject to the indexer's back-off ladder, so indexer credentials never reach SABnzbd

#### Scenario: NZB validation before upload

- **WHEN** fetched NZB bytes are validated before upload
- **THEN** they must be non-empty, parse under the NZB-specific hardened entry point (spec-conformant DOCTYPE-bearing NZBs accepted; entity-declaration payloads, external references, oversized bodies, and non-XML junk rejected), and contain at least one file segment; bytes failing any check surface as a failed grab with a reason and are never POSTed to SABnzbd

#### Scenario: addfile multipart upload records nzo_id as download_id

- **WHEN** validated NZB bytes are uploaded with `mode=addfile` as a multipart POST carrying the configured category (default "comics") and priority
- **THEN** the returned `nzo_id` is recorded as the download_id; an empty `nzo_id` response is treated as a grab failure

#### Scenario: Local-service egress to the operator base URL

- **WHEN** foragerr connects to the SABnzbd HTTP API
- **THEN** the request uses the local-service egress profile against the operator-configured base URL, distinct from the external profile used to fetch NZBs from indexers
