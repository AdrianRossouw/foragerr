# tor Spec Delta

## ADDED Requirements


### Requirement: FRG-TOR-001 — Torrent as a second protocol

The system SHALL support torrent as a second release protocol flowing through the existing indexer abstraction (Torznab), decision engine, prioritization, grab dispatch, and tracked-download state machine, with a per-delay-profile protocol enable and preferred-protocol setting.

- **Milestone**: M2
- **Source**: sonarr-arch §3.2 (ProtocolSpecification), §3.4 (delay profiles per protocol); mylar-fs TOR
- **Notes**: The M2 thesis: torrents are additive configuration over M1's seams (protocol field exists from M1), not a parallel pipeline. Torznab search itself is specified under IDX.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A Torznab release and a Newznab release for the same issue are decided by one engine and the protocol preference tiebreaks per configuration; disabling the torrent protocol rejects torrent releases with a visible reason.

### Requirement: FRG-TOR-002 — qBittorrent client

The system SHALL implement a qBittorrent download client (category, save path, optional add-paused/force-start) behind the standard download-client interface, reporting seeding items as completed-but-unremovable until seed goals are met.

- **Milestone**: M2
- **Source**: mylar-fs TOR (qBittorrent client); sonarr-arch §4.1 (client abstraction)
- **Notes**: One client for M2. qBittorrent chosen over Mylar's other five for API quality, category semantics matching SAB's, and linuxserver.io ecosystem prevalence. uTorrent/rTorrent/Transmission/Deluge → B.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A torrent grab lands in qBittorrent under the configured category, is tracked through the common queue, and imports on completion while continuing to seed.

### Requirement: FRG-TOR-003 — Magnet and .torrent handling

The system SHALL grab torrent releases by fetching the .torrent file server-side (validating and extracting the info-hash) or by magnet link where the client supports it, using the info-hash as the client download id for tracking.

- **Milestone**: M2
- **Source**: mylar-fs TOR (magnet + .torrent handling, hash computation); sonarr-arch §4.3 (download id join key)
- **Notes**: Server-side .torrent fetch mirrors the NZB addfile decision — indexer auth stays server-side.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** Both a .torrent-URL release and a magnet release resolve to a tracked download joined by info-hash.

### Requirement: FRG-TOR-004 — Seeding-aware import and removal

Import of a still-seeding torrent SHALL copy (hardlink where possible) rather than move the files, and the system SHALL remove the torrent from the client (per the remove-completed flag) only after the client reports seeding goals (ratio/time) met.

- **Milestone**: M2
- **Source**: sonarr-arch §5.3 (move vs copy on CanMoveFiles), §4.1 (CanBeRemoved/CanMoveFiles); mylar-fs TOR
- **Notes**: Seed-goal configuration delegated to the client where possible; foragerr only respects the client's removable signal.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** An imported seeding torrent keeps seeding with the library copy present; after ratio is met the client entry is removed automatically.

### Requirement: FRG-TOR-005 — Seeder-based decision and prioritization

The decision engine SHALL reject torrent releases below a configurable minimum seeder count, and prioritization SHALL include a log-bucketed peer-count comparator for torrent releases.

- **Milestone**: M2
- **Source**: sonarr-arch §3.2 (TorrentSeeding spec noted), §3.3 (peers comparator); mylar-fs TOR (MINSEEDS)
- **Notes**: Inserts into the existing comparator chain after indexer priority (protocol-conditional).

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A 0-seeder release is rejected with a visible reason; between two otherwise-equal torrents, the one with an order-of-magnitude more seeders wins.

### Requirement: FRG-TOR-006 — Blocklist by info-hash

Failed torrent downloads SHALL be blocklisted and matched primarily by info-hash, falling back to source title, through the same blocklist store and specification as usenet.

- **Milestone**: M2
- **Source**: sonarr-arch §4.6 (torrent match = info-hash or title)
- **Notes**: Extends the M1 blocklist row, no new mechanism.

#### Scenario: Baseline acceptance

- **WHEN** this requirement is verified against the implementation
- **THEN** A failed torrent's identical info-hash from a different Torznab indexer is rejected as blocklisted.
