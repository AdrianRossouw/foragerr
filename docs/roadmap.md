# Roadmap

This is the only controlled document that describes unshipped work
(**FRG-PROC-018**). Every other controlled document — `README.md`, the manual
under `docs/manual/` — describes only behavior already merged to `main`, and
links here for anything forward-looking rather than restating it.

Authoritative status for any requirement lives in the
[requirements registry](traceability/requirements-registry.md); the entries
below are **intentions, not commitments**. Each will land (if it lands) as its
own approved OpenSpec change, and sequencing or scope may shift. Where
requirement IDs are already allocated they are cited; many future items have no
IDs yet, because IDs are allocated at proposal time.

**The 1.0 cut** (owner decision 2026-07-11; amended 2026-07-22): version 1.0
is reached at the end of M10, after the sources (M6), authentication (M8),
UI refinement (M9), torrents (M7), and go-live (M10) milestones. The bar is
"safe for strangers to deploy" — authentication is the hard gate — **and,
per the 2026-07-22 amendment, acquisition-complete**: live dogfood showed
current-title completion from usenet + DDL alone falls short of the
product's core promise, so torrents move inside 1.0. M7 keeps its label
because registry rows cite it, and labels are never renumbered. It is
sequenced *inside* M10: after the release-pipeline change, before
qualification and the pentest, so 1.0's qualification and penetration test
cover the torrent surface rather than certifying a smaller product than
ships. Before 1.0, releases may still make breaking changes with migration
notes; at 1.0 the public surfaces (REST API, OPDS, configuration,
environment variables) start a clean slate under strict semantic
versioning.

## M6 — Sources

Broaden how issues you are entitled to enter the library. Two M6 changes have
shipped: the encrypted credential store — at-rest encryption for provider
secrets saved through the UI, landed before any account credential is
persisted — and the **Humble Bundle importer**, which connects your Humble
account with a pasted session cookie and brings the DRM-free comic bundles you
have purchased into your library through a review-first sync and the standard
import pipeline. Still planned:

- **Companion browser extension** — a small, copy-only helper that puts the
  Humble session cookie on the clipboard so connecting a source is a paste,
  never a stored password.

## M8 — Authentication

This milestone replaces the original no-authentication posture (the accepted
risk `RISK-020`, Tailscale-only) with a single-user login, session and API-key
handling, and uniform coverage of the UI, API, and OPDS surfaces. **Complete**:
the first change (`m8-auth-core`, v0.7.0) shipped the default-deny perimeter,
mandatory login, two-tier sessions, scrypt password hashing, env bootstrap,
the CSRF stance, and WebSocket origin validation, mitigating `RISK-020`; the
second (`m8-keys-opds`, v0.8.0) shipped the credential lifecycle — Settings →
Security password changes, API-key rotation with display-once, independent
OPDS credentials, sign-out-everywhere, and the env re-seed fingerprint
semantics; the third and last (`m8-rate-audit`, v0.9.0) shipped failed-auth
throttling (429 + growing `Retry-After`, never a lockout) and a unified
`auth.*` structured audit vocabulary across every surface, including
`auth.apikey_source_seen` leaked-key visibility.

## M9 — UI refinement

**Complete** (v0.9.1–v0.9.16, closed 2026-07-16). The polish milestone
delivered across the 0.9.x dogfood series: deferred UX items from the M4/M5
gates, design-fidelity and state-completeness passes, iPad/tablet
ergonomics, the accessibility scan in the e2e gate, credential-runtime and
health-truthfulness fixes surfaced by structured dogfood, OPDS per-issue
covers, and the public project site.

## M10 — Go-live and 1.0

**In progress** (kicked off 2026-07-17; design authority: the m10-go-live
pre-design). The release milestone: what it takes for strangers to deploy
foragerr safely, and the capstone of the regulated-development
demonstration. Sequenced as: deployment-posture hardening (shipped,
v0.9.17), then the release pipeline (GHCR publishing, dev/rc/release
channels, change control, credential scoping), then **torrents (M7,
resequenced into 1.0 — see its section)**, then V&V/qualification
(IQ/OQ/PQ), audit durability, and the pentest over the full surface.

- Deployment security posture: HTTP security headers, opt-in trusted-proxy
  handling, unauthenticated-disclosure hygiene, and the committed posture
  record (`docs/security/posture.md`).
- A formal release process: GHCR image publishing, dev/rc/release
  semantic-versioning channels, a release-level gate distinct from the
  per-change merge gate, and change control for official releases.
- The penetration-test decision (whether, scope, and by whom) made and
  recorded.
- Backup/restore and upgrade-path proofs; IQ/OQ/PQ deployment
  qualification with non-leaky records rendered on the project site.
- Manual completeness audit against the shipped feature set.
- The 1.0 compatibility promise takes effect: strict SemVer on REST, OPDS,
  configuration, and environment variables from here on.

## M7 — Torrents (in 1.0, resequenced 2026-07-22)

Moved inside the 1.0 cut by owner decision 2026-07-22 (previously the
post-1.0 flagship; the label is kept because registry rows cite it). Lands
between M10's release-pipeline change and its qualification/pentest
changes. A torrent download client alongside the existing clients, with
Torznab indexing through an existing Prowlarr/Jackett instance,
seeding-aware import, and honouring each tracker's seeding requirements
(per-torrent ratio and seed-time limits) before a completed download is
removed. The centerpiece is **pack handling**: one downloaded pack
satisfying many wanted issues (never re-fetching the same pack per issue),
with weekly packs matched against the pull list — planned as its own
capability so single-download-many-issues also benefits the existing
usenet/DDL paths, with the torrent transport layered on top.

- Requirements: `FRG-TOR-001` (torrent protocol), `FRG-TOR-002` (client),
  `FRG-TOR-003` (magnet/.torrent handling), `FRG-TOR-004` (seeding-aware
  import), `FRG-TOR-005` (seeder-based decisioning), `FRG-TOR-006` (info-hash
  blocklist), `FRG-IDX-012` (Torznab indexer support).

## Beyond — unshaped intentions

No IDs, no sequence — each still lands as its own approved change when picked
up:

- **Public-domain archive import** — bring in public-domain golden-age issues
  hosted on the Internet Archive, from operator-curated collections. Shaped as
  an indexer plus a direct-download capability riding the existing download
  engine (search, then fetch), not as an account-backed store source.
- Bundle-watching alerts for followed creators and monitored series appearing
  in public bundles; format preference as real configuration (which format to
  grab, keep, and serve); additional storefront sources; notifications.
