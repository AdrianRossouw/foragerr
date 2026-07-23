# meta — delta for fix-cover-proxy

## ADDED Requirements

### Requirement: FRG-META-021 — Proxied metadata imagery

Candidate cover imagery from the metadata provider SHALL be served to the
browser same-origin through an authenticated proxy endpoint, never
hotlinked — so the SPA's self-contained Content-Security-Policy
(FRG-SEC-006) holds while lookup and review surfaces show covers. The
proxy SHALL enforce, server-side, in order: the request is authenticated
(default-deny perimeter); the target URL is HTTPS with a host on the
ComicVine media allowlist (exact host or dot-boundary subdomain); the
fetch runs over the hardened external egress profile (FRG-SEC-001,
per-hop validation); the response is verified as an image by magic bytes
before any byte is served; a streaming size cap bounds the transfer. A
bounded in-memory cache MAY serve repeats; cache entries are keyed by
exact URL.

#### Scenario: Allowlisted cover proxies same-origin

- **WHEN** an authenticated client requests the proxy with an HTTPS ComicVine media URL
- **THEN** the image bytes are returned same-origin with the sniffed image content type, and the SPA renders it under the unchanged self-contained CSP

#### Scenario: Off-allowlist and non-HTTPS targets are refused

- **WHEN** the proxy is asked for a URL on any non-allowlisted host (including a bare-suffix lookalike of an allowlisted host) or a non-HTTPS URL
- **THEN** the request is refused with a 400 naming the constraint, and no outbound fetch is attempted

#### Scenario: Non-image content never reaches the client

- **WHEN** the allowlisted host answers with content whose magic bytes are not a known image format (HTML, JSON, text)
- **THEN** the proxy refuses with a 502-class error and serves zero body bytes to the client

#### Scenario: Unauthenticated requests are denied

- **WHEN** the proxy is requested with no session or API key
- **THEN** the perimeter rejects it with 401 before any fetch logic runs
