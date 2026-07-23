# fix-cover-proxy — restore lookup covers through a same-origin proxy

## Why

The v0.9.17 hardening set the SPA's Content-Security-Policy to
`img-src 'self' data: blob:` — correct for the recorded "fully
self-contained SPA" position, but it silently broke an existing feature:
the Add-series picker and Library-import proposals render ComicVine
candidate covers as direct `<img>` hotlinks to `comicvine.gamespot.com`,
which the browser now blocks (regression found 2026-07-23, live rig; no
test asserts a candidate cover renders, so e2e stayed green). Owner
directive: "fix the covers." The spec-conforming fix is proxying the
imagery same-origin — widening the CSP would contradict the FRG-SEC-006
scenario shipped three days ago.

## What Changes

- New authenticated endpoint `GET /api/v1/metadata/cover?src=<url>`
  (FRG-META-021): fetches a cover image from an explicitly allowlisted
  ComicVine media host over the hardened external egress profile and
  serves it same-origin. Constraints, all enforced server-side: HTTPS
  only; host must be on the CV media allowlist (dot-boundary subdomain
  match); response verified as a real image by magic bytes before a byte
  is served; streaming size cap; bounded in-memory LRU cache.
- Frontend candidate covers (Add-series picker, Library-import proposals)
  route their `image_url` through the proxy — same-origin, so the
  self-contained CSP holds unchanged.
- The perimeter's default-deny covers the route (no exempt-list change).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `meta`:
  - **ADDED** `FRG-META-021 — Proxied metadata imagery` (layered; no
    existing requirement modified. FRG-SEC-006's self-contained-SPA
    scenario is what this change RESTORES compliance-in-spirit for —
    covers render again with the policy untouched).

FRG-META-021 is allocated in the registry by this proposal.

## Impact

- **New attack surface** (FRG-PROC-006, security docs updated in this
  change): an authenticated endpoint that fetches a client-supplied URL —
  SSRF-sensitive by shape. Mitigations layered: strict host allowlist
  (only CV media hosts), HTTPS-only, the per-hop SSRF egress validator
  (FRG-SEC-001) underneath, image-magic-byte verification, size cap,
  no redirects off-allowlist (factory hop checks). Threat-model delta +
  tested abuse scenarios in the same change (tiered-gate rule for new
  surface).
- Code: new `backend/src/foragerr/api/cover_proxy.py`; frontend helper +
  two render sites; tests.
- Docs: threat-model delta; no manual change (operator-invisible).

## Non-goals

- Proxying pull-list / LOCG covers (needs the talkhard ingestion rider —
  M11; the endpoint's allowlist can grow then, per-host, by change).
- Replacing the library cover cache (FRG-META-013) — series covers keep
  their existing cached path.
- CSP changes of any kind.

## Approval

**Approved by Adrian 2026-07-23** — "fix the covers", in session, after
the two fix shapes (proxy vs CSP widening) were presented with the proxy
recommended; regression-fix under the standing bugfix grant with the new
surface handled per FRG-PROC-006.
