# SEC — Security (Cross-Cutting) Specification

## Purpose

Security-specific requirements derived from the system-wide STRIDE threat analysis
(`docs/security/threat-model.md`, FRG-PROC-006). These cover gaps the domain baseline
did not already fix; every research security flag the domain requirements *do* cover is
recorded against its governing requirement in `docs/security/risk-register.md` rather
than duplicated here. All confinement/limit controls are implemented once at shared
choke points (the outbound HTTP client factory, the archive-safety utility, the
safe-join utility) and reused across areas.
## Requirements
### Requirement: FRG-SEC-001 — SSRF egress controls for server-side fetches

Every server-side outbound HTTP(S) fetch to a host derived from external or config-supplied input — at minimum ComicVine cover/image URLs (wiki-editable), configured indexer/Torznab base URLs, the SABnzbd host, any FlareSolverr URL, and the weekly-pull source — SHALL resolve the target host and refuse to connect when it resolves to a loopback, link-local, private/RFC-1918, or otherwise non-public address unless that exact host is on an explicit operator-configured allowlist, SHALL cap and re-validate every redirect hop against the same policy, and SHALL never send one integration's credentials or cookies to a host outside that integration's allowlist.

- **Milestone**: M1
- **Source**: STRIDE analysis extending mylar-ddl.md §4 (SSRF via scraped links — drafts fix DDL only) and mylar-comicvine.md §4 (server-fetched wiki-controlled image URLs). Gap G-3; RISK-025, RISK-039.
- **Notes**: Generalizes the DDL per-provider allowlist (FRG-DDL outbound URL security) to the ComicVine image fetch and all config-URL integrations. Implemented at the single shared HTTP client factory FRG-NFR already mandates — one choke point.

#### Scenario: Per-hop egress validation refuses non-public addresses

- **WHEN** an `external`-profile fetch targets a URL whose scheme is not `http`/`https`, or whose host DNS-resolves to any address that is loopback, link-local, RFC-1918 private, or IPv6 ULA (including hosts with multiple A/AAAA records where only one is private)
- **THEN** the request is refused before any connection is made, with a logged policy-violation error identifying the offending resolved address; a public-resolving host passes

#### Scenario: Every redirect hop is re-validated

- **WHEN** a fetch to a public host returns a redirect whose Location points at a private, loopback, or link-local target (directly or via a DNS name resolving there)
- **THEN** the manual redirect walk (FRG-NFR-006) re-runs the full egress validation on that hop and drops the redirect with a bounded error; no connection to the private target occurs and no credentials/cookies from the originating integration are sent to the redirect host

#### Scenario: Hostile-fixture corpus is refused

- **WHEN** the egress validator is exercised against a hostile fixture set: IP-literal loopback (`http://127.0.0.1/…`, `http://[::1]/…`), decimal-encoded (`http://2130706433/`) and hex-encoded (`http://0x7f000001/`) IP forms, and a ComicVine response whose image URL points at an internal address
- **THEN** every fixture is refused by the `external` profile with no outbound connection attempted, and the refusals are asserted at the shared-client choke point (no bypass path)

#### Scenario: local-service profile permits operator-configured LAN targets; rebinding residual is documented

- **WHEN** an integration whose base URL is operator-configured (e.g., SABnzbd on a LAN/RFC-1918 address) is used via the `local-service` client profile, and the same private address is attempted via the default `external` profile
- **THEN** the `local-service` fetch to the configured base URL succeeds while the `external`-profile attempt is refused; and the DNS-rebinding TOCTOU window (resolve-then-connect) is recorded as an accepted residual in `docs/security/risk-register.md` (RISK-025 note) rather than claimed as mitigated

### Requirement: FRG-SEC-002 — Hardened XML parsing (XXE / entity-expansion)

All parsing of untrusted XML — Newznab/Torznab RSS and error responses, CBL reading-list imports, and any XML accepted on an OPDS or API surface — SHALL use a parser configured with external-entity resolution disabled, DTD/DOCTYPE processing disabled, and entity-expansion bounded, such that no external entity is fetched and no entity-expansion (billion-laughs) can exhaust memory or CPU.

- **Milestone**: M1
- **Source**: mylar-comicvine.md §4 (minidom/expat entity-expansion note) + STRIDE analysis (Newznab responses are untrusted XML; FRG-IDX response parsing states no hardening; CBL noted only in ARC Notes). Gap G-2; RISK-024, RISK-035, RISK-037.
- **Notes**: ComicVine moves to JSON (removing that XML surface); the live residual is the indexer RSS/XML parser (M1) and CBL (backlog). Prefer `defusedxml` or an equivalently configured parser project-wide.

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

### Requirement: FRG-SEC-003 — Archive-processing safety (bomb / zip-slip limits)

Every operation that opens, decompresses, extracts, or rewrites a comic archive (import-time validity/image checks, cover/first-page extraction, OPDS page streaming, pack extraction, and in-process ComicInfo.xml tagging) SHALL enforce configurable limits — maximum member count, maximum per-member and total decompressed size, and image pixel-dimension caps before decode — and SHALL reject any archive member whose name contains a path-separator escape, absolute path, or symlink/hardlink, writing extracted or rewritten content only inside a confined staging or target directory.

- **Milestone**: M1
- **Source**: mylar-opds.md §5 S5 + mylar-ddl.md §4 (extraction/bomb concerns drafts scope to OPDS and DDL packs only). Gap G-4; RISK-010, RISK-008 (non-DDL paths), RISK-005 (import/cover image decode).
- **Notes**: Consolidates the hoist hints in FRG-OPDS resource limits and the pack-scoped FRG-DDL safe extraction. FRG-PP archive validity checks structure but states no bomb caps; cover extraction and tagging write by member name (zip-slip). One shared archive-safety utility serves IMP, PP, OPDS, and DDL.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A zip-bomb and a zip containing `../`/absolute/symlink members are each rejected with a bounded, logged failure on the import, cover-extraction, and tagging paths (not only DDL/OPDS); no file is written outside the intended directory; limits are configurable.

### Requirement: FRG-SEC-004 — Filesystem path confinement (safe-join)

Every filesystem path the system constructs from external or derived input — series/issue destination folders and filenames (from ComicVine-derived titles), cover-cache file paths, manual-import target paths, and download-client-reported paths after remote mapping — SHALL be produced through a single safe-join utility that normalizes the result and guarantees it remains within the configured managed root (library root, `/config` cache, or download staging), refusing any input that would escape confinement.

- **Milestone**: M1
- **Source**: STRIDE analysis (only FRG-OPDS library-id resolution and FRG-DDL safe filename generation have explicit confinement; rename/move/cover paths rely on illegal-char policy without a central containment guarantee). Gap G-4a; RISK-019, RISK-029.
- **Notes**: Complements FRG-META untrusted-input sanitization and FRG-PP token renaming / safe file operations by adding the containment invariant they assume but do not state. Pairs with FRG-SEC-003.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A ComicVine series title containing `../`, an absolute path, or a reserved/device name yields a sanitized path inside the library root (or a rejected-with-reason import), never a write outside the root; a path-escape corpus passes for import, rename/move, and cover-cache writes.

### Requirement: FRG-SEC-005 — CSRF stance and WebSocket Origin validation

Once authentication is enabled, all state-changing HTTP endpoints SHALL be protected against cross-site request forgery (via API-key-header-only auth for programmatic clients and an explicit SameSite/anti-CSRF stance for the cookie-session UI), and the WebSocket handshake SHALL validate the request Origin against an allowlist, refusing cross-origin socket connections.

- **Milestone**: M3
- **Source**: STRIDE analysis (WebSocket auth required by FRG-AUTH uniform surface coverage, but Origin/CSWSH and API CSRF stance unaddressed). Gap G-5; RISK-022.
- **Notes**: Rides with the AUTH milestone. Before M3 the tailnet is the boundary (RISK-020, owned by FRG-AUTH); this prevents a browser-resident attacker abusing the operator's session once auth exists.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A forged cross-site POST from a foreign origin using only ambient cookies is rejected (or impossible because state-changing routes require the API-key header); a WebSocket handshake with a disallowed Origin is refused; exempt/allowed origins are covered by tests.

