# sec Spec Delta

## MODIFIED Requirements

### Requirement: FRG-SEC-002 — Hardened XML parsing (XXE / entity-expansion)

All parsing of untrusted XML — Newznab/Torznab RSS and error responses, CBL reading-list imports, and any XML accepted on an OPDS or API surface — SHALL use a parser configured with external-entity resolution disabled, DTD/DOCTYPE processing disabled, and entity-expansion bounded, such that no external entity is fetched and no entity-expansion (billion-laughs) can exhaust memory or CPU. Exactly one carve-out exists: **NZB payloads**, whose format specification mandates a `<!DOCTYPE nzb PUBLIC "-//newzBin//DTD NZB 1.1//EN" ...>` header, SHALL be parsed via a dedicated NZB entry point that tolerates an inert DOCTYPE declaration while keeping entity declarations rejected, external resolution disabled, and the parse byte-bounded — the DOCTYPE's PUBLIC/SYSTEM identifier is never fetched. The NZB entry point SHALL live in the same single sanctioned parser-construction module as the general hardened parse, and no non-NZB surface may use it.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §4 (minidom/expat entity-expansion note) +
  STRIDE analysis (Newznab responses are untrusted XML; FRG-IDX response
  parsing states no hardening; CBL noted only in ARC Notes). Gap G-2; RISK-024,
  RISK-035, RISK-037.
- **Notes**: ComicVine moves to JSON (removing that XML surface); the live
  residual is the indexer RSS/XML parser (M1) and CBL (backlog). Prefer
  `defusedxml` or an equivalently configured parser project-wide. Amended by
  v0-6-3-fixes (live-SABnzbd finding, 2026-07-12): the blanket DOCTYPE ban
  rejected every spec-conformant NZB, so no real usenet grab could ever reach
  SABnzbd; the carve-out keeps every attack-bearing property forbidden —
  RISK-024/035/037 mitigations are unaffected.

#### Scenario: Billion-laughs / quadratic-blowup entity expansion is rejected without resource exhaustion

- **WHEN** a Newznab RSS response containing a nested-entity bomb (billion-laughs) or a quadratic-blowup entity-expansion payload is fed to the indexer XML parser
- **THEN** parsing terminates with a typed parse failure (not a crash or hang) and the process does not exhaust memory or CPU beyond bounded limits, and no partial result is returned to the caller

#### Scenario: External entity (file / URL) resolution is disabled — no exfiltration

- **WHEN** a Newznab RSS response references an external entity pointing at a local file path (e.g. `file:///etc/passwd`) or an outbound URL
- **THEN** the parser resolves no external entity: no file is read and no outbound network fetch is issued, and the document is rejected as a typed parse failure

#### Scenario: Oversized document and junk bytes fail as typed parse errors

- **WHEN** an indexer response exceeds the outbound HTTP client factory's byte cap, or the body is non-XML junk bytes
- **THEN** the read is bounded at the factory byte cap and the parse fails with a typed error, with no memory blow-up, no crash, and no network fetch or file read

#### Scenario: No XML parser is constructed with entity resolution enabled

- **WHEN** the codebase is statically checked for XML parser construction
- **THEN** every untrusted-XML parse site is routed through the hardened (defusedxml-configured) parser with DTD/DOCTYPE processing and external-entity resolution disabled, and no parser is constructed with entity resolution enabled

#### Scenario: Spec-conformant NZB DOCTYPE is inert, entity bombs inside it are not

- **WHEN** NZB bytes carrying the spec-mandated newzBin DOCTYPE are validated for grab, and separately NZB bytes whose DOCTYPE contains `<!ENTITY>` declarations (an entity bomb) are validated
- **THEN** the spec-conformant NZB parses successfully with no external fetch of the DOCTYPE identifier, while the entity-bearing NZB terminates with a typed validation failure and is never POSTed to SABnzbd
