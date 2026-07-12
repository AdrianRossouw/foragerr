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

Broaden how issues you are entitled to enter the library. The encrypted
credential store — at-rest encryption for provider secrets saved through the UI —
has shipped as the first M6 change, before any account credential is persisted.
Still planned:

- **Humble Bundle importer** — unpack the DRM-free comic bundles you have
  purchased from Humble Bundle straight into your library.
- **Companion browser extension** — a small, copy-only helper that puts the
  Humble session cookie on the clipboard so connecting a source is a paste,
  never a stored password.

## M8 — Authentication

foragerr currently ships with no authentication and is operated Tailscale-only;
that posture is an explicitly accepted risk (`RISK-020`), scheduled to be
replaced, not kept forever. This milestone adds a single-user login, session
and API-key handling, and uniform coverage of the UI, API, and OPDS surfaces.
Its implementation requires fresh owner approval before work begins.

- Requirements: `FRG-AUTH-002` (login), `FRG-AUTH-003` (password KDF),
  `FRG-AUTH-004` (sessions), `FRG-AUTH-005` (OPDS Basic realm), `FRG-AUTH-006`
  (API keys), `FRG-AUTH-007` (key lifecycle), `FRG-AUTH-009` (rate
  limiting/audit), `FRG-AUTH-010` (uniform coverage), `FRG-SEC-005` (CSRF
  stance and WebSocket origin validation).

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
