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

## M5 — Creators & follows

Follow the writers and artists behind the comics you own, and browse their work
both inside your library and across ComicVine's catalogue, as a way to decide
what to add next. Requirement IDs will be allocated when this milestone is
proposed.

## M6 — Sources

Broaden how issues you are entitled to enter the library:

- **Encrypted credential store first** — at-rest encryption for provider
  secrets saved through the UI, landing before any account credential is
  persisted (`FRG-AUTH-008`).
- **Humble Bundle importer** — unpack the DRM-free comic bundles you have
  purchased from Humble Bundle straight into your library.
- **archive.org importer** — bring in public-domain issues hosted on the
  Internet Archive.

## M7 — Torrents

Add a torrent download client (qBittorrent) alongside the existing clients,
with Torznab indexing through an existing Prowlarr/Jackett instance, and honour
each tracker's seeding requirements (per-torrent ratio and seed-time limits)
before a completed download is removed.

- Requirements: `FRG-TOR-001` (torrent protocol), `FRG-TOR-002` (client),
  `FRG-TOR-003` (magnet/.torrent handling), `FRG-TOR-004` (seeding-aware
  import), `FRG-TOR-005` (seeder-based decisioning), `FRG-TOR-006` (info-hash
  blocklist), `FRG-IDX-012` (Torznab indexer support).

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
