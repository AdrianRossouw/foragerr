## MODIFIED Requirements

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
