# m7-torrents — torrent protocol, seeding lifecycle, and packs (milestone pre-design)

## Why

Torrents are the flagship post-1.0 feature (owner 1.0-cut decision, 2026-07-11:
M7 moves past 1.0, label retained). This change record was **pre-designed
2026-07-11** while top-tier design capacity was available; it is the design
authority for the milestone and is NOT apply-ready by intent — at M7 kickoff it
splits into implementable changes (decomposition below), each with its own
delta specs, tasks, and approval.

Two owner decisions shape it beyond the approved TOR-001..006 baseline:
- **Packs are in scope from the start.** Comic torrents are dominated by
  whole-run packs and **weekly packs** mirroring the pull list — a gap in Mylar
  too. The pipeline is designed 1-download→N-issues from day one, including
  finding the right weekly pack *from* the pull list.
- **Stall behavior follows Sonarr/Radarr**: stalled torrents are loud warnings
  (queue + health), never silent; auto-fail is an opt-in knob shipping OFF.

## What Changes

- **BREAKING (vs approved spec, amendment required)**: FRG-TOR-002's client
  becomes **Transmission** (owner direction 2026-07-10 reshape + 2026-07-11),
  replacing qBittorrent; registry-legend wording syncs in the same change.
- Torznab indexers (FRG-IDX-012) through the existing indexer abstraction;
  protocol preference and delay-profile handling (FRG-TOR-001); seeder gates
  and peer comparator (FRG-TOR-005).
- Transmission download client behind the existing `DownloadClient` protocol;
  .torrent/magnet grab with info-hash tracking (FRG-TOR-003).
- Seeding-aware lifecycle: import-while-seeding via hardlink/copy, goal-met
  removal (FRG-TOR-004); blocklist by info-hash (FRG-TOR-006).
- Pack support: release classification, pack-aware decisioning, 1→N import,
  weekly-pack ↔ pull-list integration (**new requirement ids allocated at the
  implementing change's proposal**, per the registry lesson — none allocated by
  this pre-design).

## Capabilities

Declared for orientation; delta specs are written by the implementing changes,
not this record: `tor` (all six requirements gain scenario-level elaboration;
TOR-002 amended to Transmission), `idx` (IDX-012), `dl` (ClientItem protocol
extension), `imp`/`pp` (hardlink/copy import mode, pack import), `pull`
(weekly-pack matching), `ui` (queue seeding presentation), plus new pack ids.

## Decomposition at M7 kickoff (~gate-sized)

1. `m7-torznab-grab` — Torznab search/caps, seeder gates, protocol preference,
   .torrent/magnet grab, info-hash, bencode parsing (STRIDE + SOUP decision).
2. `m7-seeding-lifecycle` — Transmission client, ClientItem extension,
   import-while-seeding, goal-met removal, stall/error classification. The
   hard one; the state-machine design below is primarily for this change.
3. `m7-packs` — classification, pack decisioning, 1→N import, junk tolerance.
4. `m7-weekly-pull-packs` — pull-week → weekly-pack search/match/grab (may
   fold into 3 if small).

## Impact

New attack surface at implementation: bencode parser (untrusted input),
Transmission RPC (credentialed outbound; secrets via the M6 keystore),
tracker announce URLs carry private passkeys (secrets — redaction + never
logged). Each implementing change carries its STRIDE/risk updates
(FRG-PROC-006). Disk-usage note: seeding retention + pack imports mean
copies; documented budget guidance in the manual.

## Non-goals

- qBittorrent/Deluge/rTorrent clients (Transmission only; others → B).
- Public-tracker RSS aggregation, DHT search, or any non-Torznab discovery.
- Cross-seeding management, torrent creation/upload.
- archive.org (separate direction: indexer + DDL capability, see memory).

## Approval

_Pre-design record only — reviewed by Adrian 2026-07-11 (decisions: packs in
scope incl. weekly-pull integration; Sonarr/Radarr stall parity; Transmission).
Implementation approval happens per implementing change at M7 kickoff
(FRG-PROC-009)._
