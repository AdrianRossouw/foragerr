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

**The 1.0 cut** (owner decision, 2026-07-11): version 1.0 is reached at the end
of M10, after the sources (M6), authentication (M8), UI refinement (M9), and
go-live (M10) milestones. The bar is "safe for strangers to deploy" —
authentication is the hard gate. Torrents (M7) move past 1.0 in sequence; the
milestone keeps its label because registry rows cite it, and labels are never
renumbered. Before 1.0, releases may still make breaking changes with migration
notes; at 1.0 the public surfaces (REST API, OPDS, configuration, environment
variables) start a clean slate under strict semantic versioning.

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

A dedicated polish milestone, placed after authentication because auth is the
last milestone that adds screens (login, sessions, and API-key management get
polished alongside everything else). Scope seeds — final scope set at proposal
time, likely against a fresh design handoff:

- Deferred UX items carried from the M4/M5 gates (bulk-monitor
  discoverability, shift-range selection, overview show-more, and the rest of
  the deferred-items lists in the archived change proposals).
- A design-handoff fidelity audit across all shipped screens.
- State completeness: empty, error, loading, and first-run states everywhere.
- iPad/tablet ergonomics (OPDS reading is iPad-first; the management UI is
  desktop-dense today).
- Keyboard and accessibility pass; UI-responsiveness re-verification at the
  full feature set; README screenshot refresh as the closing act.
- A deliberate API/configuration warts review, so 1.0's clean slate starts
  clean.

## M10 — Go-live and 1.0

The release milestone: what it takes for strangers to deploy foragerr safely,
and the capstone of the regulated-development demonstration.

- A formal release process: dev/rc/release semantic-versioning scheme and a
  release-level gate distinct from the per-change merge gate.
- The penetration-test decision (whether, scope, and by whom) made and
  recorded.
- Backup/restore and upgrade-path proofs.
- Manual completeness audit against the shipped feature set.
- The 1.0 compatibility promise takes effect: strict SemVer on REST, OPDS,
  configuration, and environment variables from here on.

## M7 — Torrents (post-1.0)

The first milestone after 1.0 and its flagship feature; the label predates the
1.0 cut and is kept because registry rows cite it. A torrent download client
alongside the existing clients, with Torznab indexing through an existing
Prowlarr/Jackett instance, seeding-aware import, and honouring each tracker's
seeding requirements (per-torrent ratio and seed-time limits) before a
completed download is removed. Run packs — the season-pack analogue that
dominates comic torrents — are in scope.

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
