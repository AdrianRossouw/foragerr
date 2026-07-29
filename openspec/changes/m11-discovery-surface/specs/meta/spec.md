# meta — delta for m11-discovery-surface

## MODIFIED Requirements

### Requirement: FRG-META-021 — Proxied metadata imagery

Candidate and pull cover imagery SHALL be served to the browser
same-origin through an authenticated proxy endpoint, never hotlinked —
so the SPA's self-contained Content-Security-Policy (FRG-SEC-006)
holds while lookup, review, and Calendar surfaces show covers. The
proxy's allowlist SHALL consist of per-host **rules** — each naming a
host, a subdomain policy, and an optional required path prefix — fixed
in code (grown per host, by change, never by configuration):

- the ComicVine media hosts, matched exact or dot-boundary subdomain,
  no path constraint (unchanged behavior);
- the LOCG cover store on the shared S3 endpoint `s3.amazonaws.com`,
  matched **exact host only** — no subdomain form, including
  virtual-hosted bucket subdomains, is accepted — with required path
  prefix `/comicgeeks/` matched on a directory boundary.

The proxy SHALL enforce, server-side, in order: the request is
authenticated (default-deny perimeter); the target URL is HTTPS and
satisfies an allowlist rule, where the path is percent-decoded once
and refused outright if any dot-segment or backslash remains before
the prefix comparison; the fetch runs over the hardened external
egress profile (FRG-SEC-001) with **every redirect hop re-evaluated
against the same rules**; the response is verified as an image by
magic bytes before any byte is served; a streaming size cap bounds the
transfer. A bounded in-memory cache MAY serve repeats; cache entries
are keyed by exact canonicalized URL.

- **Milestone**: 0.9.x (fix-cover-proxy); rule shape + LOCG entry in
  M11 (m11-discovery-surface).
- **Source**: FRG-SEC-006 self-contained CSP; rig finding #16 and the
  2026-07-23 cover-URL facts; live verification 2026-07-29 that the
  LOCG covers live path-style on the shared S3 endpoint and that the
  same objects resolve virtual-hosted (`comicgeeks.s3.amazonaws.com`)
  — a bare-host or subdomain-matched entry would proxy any public S3
  bucket on the internet.
- **Notes**: One rule evaluator is the single source of truth, shared
  by the request-time check, the per-hop redirect check, and the pull
  ingest's fail-closed cover validation (FRG-PULL-011). Security
  posture: RISK-025 (SSRF) extended for the shared-host entry;
  threat-model delta recorded in the same change.

#### Scenario: Allowlisted cover proxies same-origin

- **WHEN** an authenticated client requests the proxy with an HTTPS
  ComicVine media URL, or an HTTPS `s3.amazonaws.com` URL under
  `/comicgeeks/`
- **THEN** the image bytes are returned same-origin with the sniffed
  image content type, and the SPA renders it under the unchanged
  self-contained CSP

#### Scenario: Off-allowlist and non-HTTPS targets are refused

- **WHEN** the proxy is asked for a URL on any non-allowlisted host
  (including a bare-suffix lookalike of an allowlisted host) or a
  non-HTTPS URL
- **THEN** the request is refused with a 400 naming the constraint,
  and no outbound fetch is attempted

#### Scenario: Shared-host paths outside the required prefix are refused

- **WHEN** the proxy is asked for an `s3.amazonaws.com` URL whose
  decoded path is not under `/comicgeeks/` on a directory boundary —
  another bucket, a prefix lookalike such as `/comicgeeks-evil/`, or a
  dot-segment/encoded-traversal path such as
  `/comicgeeks/../other-bucket/x.jpg`
- **THEN** the request is refused with a 400 before any outbound
  fetch, the traversal-bearing path being refused outright regardless
  of where it would resolve

#### Scenario: Bucket subdomains of the shared host are refused

- **WHEN** the proxy is asked for a URL on
  `comicgeeks.s3.amazonaws.com` or any other subdomain of the shared
  S3 endpoint
- **THEN** the request is refused with a 400 — the LOCG rule matches
  the exact host only, so virtual-hosted bucket addressing cannot
  bypass the path constraint

#### Scenario: A redirect hop cannot escape the rules

- **WHEN** an allowlisted target answers with a redirect to a
  different host, or to a shared-host path outside the required prefix
- **THEN** the hop is refused mid-flight by the same rule evaluation
  and zero body bytes are served

#### Scenario: Non-image content never reaches the client

- **WHEN** an allowlisted host answers with content whose magic bytes
  are not a known image format (HTML, JSON, text)
- **THEN** the proxy refuses with a 502-class error and serves zero
  body bytes to the client

#### Scenario: Unauthenticated requests are denied

- **WHEN** the proxy is requested with no session or API key
- **THEN** the perimeter rejects it with 401 before any fetch logic
  runs
