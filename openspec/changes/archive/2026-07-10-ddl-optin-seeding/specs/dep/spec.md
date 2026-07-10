# dep delta — ddl-optin-seeding

## MODIFIED Requirements

### Requirement: FRG-DEP-013 — First-run default DDL provider seeding

On a first-run (fresh) installation the system SHALL seed exactly one **disabled** GetComics DDL indexer row (`implementation="getcomics"`, `protocol="ddl"`, with the built-in default GetComics settings, `enabled=false` and automatic-search/RSS usage toggles off) AND exactly one **disabled** built-in DDL download-client row (`implementation="ddl"`, `protocol="ddl"`, with the built-in default DDL client settings, `enabled=false`), so that a keyless search→grab→download pipeline is pre-configured and discoverable in Settings but performs NO outbound acquisition activity (no search, scrape, grab, or download) until the operator deliberately enables it. The system SHALL record that first-run seeding has run via a **persisted marker** (NOT a "tables are empty" test), so that a seeded provider the user later deletes is NEVER resurrected on a subsequent restart, and seeding SHALL run at most once per database. An **established** installation upgrading from a prior version (one that already carries user configuration) SHALL be marked as seeded WITHOUT injecting any provider rows, and an installation whose seeded rows are already enabled SHALL NOT have them disabled retroactively. The system SHALL NOT seed any Newznab indexer or SABnzbd download client — credentialed providers remain opt-in.

- **Milestone**: M2 (posture amended by ddl-optin-seeding, 2026-07-09)
- **Source**: mylar-feature-surface.md (first-run usability — a fresh install should have a working default pipeline); FRG-QUAL-002 (the first-run seed precedent — a forward-only, once-per-database seed that a user deletion is not undone by); FRG-IDX-001 (indexer row model), FRG-DL-002 (download-client row model), FRG-DDL-001/FRG-DDL-002 (the built-in DDL client + GetComics provider being seeded); ddl-optin-seeding proposal (2026-07-09 fresh-install auto-grab incident).
- **Notes**: The seeded rows use the EXISTING `indexers` and `download_clients` tables unchanged — only a first-run marker is added (a forward-only migration). The DDL registry (`getcomics`/`ddl` implementations) is populated at `import foragerr.ddl` time, so the seed runs as a startup provisioning step after that import and after migrations, keyed on the marker; the reserved row name (`"GetComics"`) gives an idempotent `WHERE NOT EXISTS` guard as belt-and-suspenders. Default settings come from the models: GetComics `base_url="https://getcomics.org"`, `min_interval_seconds=15`, `max_pages=3`; built-in DDL client `host_priority="main,mirror,pixeldrain,mediafire,mega"`, `prefer_upscaled=True`. Security (FRG-PROC-006): getcomics.org remains on the per-provider `KNOWN_DDL_HOSTS` allowlist; seeding disabled returns the accepted RISK-015 (single getcomics upstream) and RISK-016 (ToS-sensitive scraping) posture from default-on to opt-in — recorded as a risk-register delta in the ddl-optin-seeding change, with the 2026-07-09 fresh-install auto-grab incident as the triggering event.

#### Scenario: A fresh install seeds one disabled GetComics indexer and one disabled DDL client

- **WHEN** the application starts for the first time against a freshly initialized (empty) database
- **THEN** after startup provisioning the `indexers` table contains exactly one row with `implementation="getcomics"` and `protocol="ddl"` that is disabled with its automatic-search and RSS usage toggles off, and the `download_clients` table contains exactly one disabled row with `implementation="ddl"` and `protocol="ddl"`, each carrying the built-in default settings, and the first-run seed marker is set

#### Scenario: A fresh install performs no acquisition traffic before opt-in

- **WHEN** a freshly seeded installation acquires wanted issues (e.g., a library import creates missing monitored issues) and the operator has not enabled the seeded provider pair
- **THEN** no search, scrape, grab, or download request is issued to the DDL upstream — the wanted issues simply remain wanted until the operator enables the seeded indexer and client

#### Scenario: Enabling the seeded pair activates the pipeline unchanged

- **WHEN** the operator enables the seeded GetComics indexer and built-in DDL client in Settings
- **THEN** the keyless search→grab→download pipeline behaves exactly as it did under the default-enabled posture, with no additional configuration required

#### Scenario: A deleted seeded provider is not resurrected on restart

- **WHEN** the seeded GetComics indexer (or DDL client) row is deleted by the user and the application is restarted
- **THEN** the deleted row is NOT recreated, because the persisted first-run marker (not a table-empty test) already records that seeding has run

#### Scenario: An established installation is not injected with providers

- **WHEN** an existing installation that already carries user configuration upgrades across this change and starts up
- **THEN** the first-run marker is set WITHOUT inserting any GetComics indexer or DDL client row, so an operator who deliberately runs without a DDL provider is never injected with one

#### Scenario: An already-enabled seeded pair is never retroactively disabled

- **WHEN** an installation seeded under the earlier default-enabled posture (rows enabled, marker set) upgrades across this change and starts up
- **THEN** the enabled rows are left exactly as they are — the opt-in posture applies to new seeds only

#### Scenario: Newznab and SABnzbd are never seeded

- **WHEN** first-run seeding runs
- **THEN** no Newznab indexer row and no SABnzbd download-client row is created — only the keyless GetComics/built-in-DDL pair is seeded (disabled), and credentialed providers remain opt-in
