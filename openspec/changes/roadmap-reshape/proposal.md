# roadmap-reshape — M4 design refresh, M5 creators, M6 sources, M7 torrents, M8 auth

## Why

The 2026-07-10 design-handoff review established that the redesigned UI (app
shell, tokens, library views, series detail, agenda-style pull screen,
creators) is a milestone of work in itself, and that the pull experience —
M3's one remaining change — presupposes the new shell, so building it in the
current UI means building it twice. Separately, the sources milestone
(Humble Bundle importer) stores real store-account credentials, which pulls
at-rest secret encryption (FRG-AUTH-008) forward, and the owner promoted
torrents (Transmission, with tracker-etiquette seeding controls) ahead of
application auth. This change re-legends the roadmap accordingly; it is the
same owner-approved reshaping mechanism as 2026-07-05.

## What Changes

- **M3 closes by rescoping**: FRG-UI-018 and FRG-PULL-007..009 move M3 → M4
  (registry rows + spec milestone bullets). M3's shipped scope (pull backbone,
  volume grouping, trade typing, OPDS page streaming) is complete.
- **M4 = design refresh** (~6 changes): design tokens + app shell; library
  three-view; series detail incl. the trade "collected in" containment model
  (promoted from backlog); Add New flow; the pull experience (absorbed ch2);
  wanted/activity/settings alignment + one-command README screenshot refresh
  tooling (per the 2026-07-10 owner instruction).
- **M5 = creators & follows**: new `CRTR` AREA row in the commit-standard
  table; requirement IDs allocated at that milestone's proposals.
- **M6 = sources**: FRG-AUTH-008 moves M5 → M6 and lands FIRST (encrypted
  credential store, key from environment only per the recorded owner
  direction, existing provider keys migrated), then the Humble Bundle
  importer, then an archive.org importer.
- **M7 = torrents**: FRG-TOR-001..006 and FRG-IDX-012 promoted B → M7.
  Torrent indexers are **Torznab-only** (owner decision 2026-07-10): foragerr
  implements the one generic protocol and users bring Prowlarr/Jackett for
  tracker connectivity — no native per-tracker implementations. Client:
  Transmission first (FRG-TOR-002 currently names qBittorrent; the M7
  proposal will carry the delta adjusting client priority — IDs never
  renumber). Per-torrent ratio/seed-time limits are core scope.
- **M8 = auth**: FRG-AUTH-002..007, 009, 010 and FRG-SEC-005 move M5 → M8.
  **Implementation beyond M7 requires fresh owner approval** (the 2026-07-10
  standing grant ends after torrents merge).
- **RISK-020 re-acceptance**: the risk register records the owner's conscious
  2026-07-10 re-acceptance of the no-auth posture through M7 on a public
  codebase (Tailscale-only exposure unchanged).
- **Codex ninth angle made official**: merge-gate checklist item 6 now names
  an independent-model (Codex) full-diff review as a required perspective in
  the review cycle (owner instruction 2026-07-10; it has caught real findings
  at three consecutive gates).

## Non-goals

- No feature implementation — planning/process/labelling docs only.
- No requirement text changes (milestone metadata moves only; the
  Transmission/qBittorrent adjustment is the M7 proposal's delta).
- No change to the M8 auth scope itself.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `auth`: FRG-AUTH-008 — milestone M5→M6 with the env-only-key requirement
  sharpened (key never persisted to a file; migration and rotation notes).
- `dev-process`: FRG-PROC-011 — the README is explicitly a controlled document
  on the same footing as the manual: any change altering a fact the README
  states updates it in the same change (owner instruction 2026-07-10), with a
  doc-consistency test pinning roadmap milestone labels to the registry.

(Other milestone moves are metadata only — spec `Milestone:` bullets updated
in place to match the registry, keeping `tools/trace.py` drift-free.)

## Impact

- `docs/traceability/requirements-registry.md` — milestone legend rewritten
  (dated, owner-approved); rows moved: UI-018/PULL-007..009 → M4,
  AUTH-008 → M6, TOR-001..006 + IDX-012 → M7, AUTH-002..007/009/010 +
  SEC-005 → M8.
- Baseline spec `Milestone:` bullets updated to match (ui, pull, auth, tor,
  idx, sec).
- `docs/process/commit-standard.md` — `CRTR` AREA row; checklist item 6 names
  the independent-model ninth angle.
- `docs/security/risk-register.md` — RISK-020 re-acceptance note.
- Manual impact (FRG-PROC-011): README Roadmap section updated to the new
  milestone shape (the requirement this change itself sharpens); no
  `docs/manual/` sections affected.
- SOUP (FRG-PROC-012): none.

## Approval

Approved by Adrian, 2026-07-10 ("i approve the roadmap reshape proposal"),
with a standing grant to run autonomously through M4–M7 ("keep going up to
just before the starting the auth milestone. until after torrents are
merged"). M8 auth implementation requires fresh approval.
