# dep — delta for m2-first-run-defaults

## ADDED Requirements

### Requirement: FRG-DEP-013 — First-run default DDL provider seeding

On a first-run (fresh) installation the system SHALL seed exactly one **enabled**
GetComics DDL indexer row (`implementation="getcomics"`, `protocol="ddl"`, with
the built-in default GetComics settings) AND exactly one **enabled** built-in DDL
download-client row (`implementation="ddl"`, `protocol="ddl"`, with the built-in
default DDL client settings), so that a keyless search→grab→download pipeline is
usable out of the box. The system SHALL record that first-run seeding has run via
a **persisted marker** (NOT a "tables are empty" test), so that a seeded provider
the user later deletes is NEVER resurrected on a subsequent restart, and seeding
SHALL run at most once per database. An **established** installation upgrading
from a prior version (one that already carries user configuration) SHALL be marked
as seeded WITHOUT injecting any provider rows. The system SHALL NOT seed any
Newznab indexer or SABnzbd download client — credentialed providers remain opt-in.

- **Milestone**: M2
- **Source**: mylar-feature-surface.md (first-run usability — a fresh install
  should have a working default pipeline); FRG-QUAL-002 (the first-run seed
  precedent — a forward-only, once-per-database seed that a user deletion is not
  undone by); FRG-IDX-001 (indexer row model), FRG-DL-002 (download-client row
  model), FRG-DDL-001/FRG-DDL-002 (the built-in DDL client + GetComics provider
  being seeded).
- **Notes**: The seeded rows use the EXISTING `indexers` and `download_clients`
  tables unchanged — only a first-run marker is added (a forward-only migration).
  The DDL registry (`getcomics`/`ddl` implementations) is populated at
  `import foragerr.ddl` time, so the seed runs as a startup provisioning step
  after that import and after migrations, keyed on the marker; the reserved row
  name (`"GetComics"`) gives an idempotent `WHERE NOT EXISTS` guard as
  belt-and-suspenders. Default settings come from the models: GetComics
  `base_url="https://getcomics.org"`, `min_interval_seconds=15`, `max_pages=3`;
  built-in DDL client `host_priority="main,mirror,pixeldrain,mediafire,mega"`,
  `prefer_upscaled=True`. Security (FRG-PROC-006): getcomics.org is already on the
  per-provider `KNOWN_DDL_HOSTS` allowlist and its default `base_url` is public, so
  NO egress/allowlist change is needed; default-enabling shifts the accepted
  RISK-015 (single getcomics upstream) and RISK-016 (ToS-sensitive scraping)
  posture from opt-in to default-on, recorded as a threat-model + risk-register
  delta in this change.

#### Scenario: A fresh install seeds one enabled GetComics indexer and one enabled DDL client

- **WHEN** the application starts for the first time against a freshly initialized
  (empty) database
- **THEN** after startup provisioning the `indexers` table contains exactly one
  enabled row with `implementation="getcomics"` and `protocol="ddl"`, and the
  `download_clients` table contains exactly one enabled row with
  `implementation="ddl"` and `protocol="ddl"`, each carrying the built-in default
  settings, and the first-run seed marker is set

#### Scenario: A deleted seeded provider is not resurrected on restart

- **WHEN** the seeded GetComics indexer (or DDL client) row is deleted by the user
  and the application is restarted
- **THEN** the deleted row is NOT recreated, because the persisted first-run marker
  (not a table-empty test) already records that seeding has run

#### Scenario: An established installation is not injected with providers

- **WHEN** an existing installation that already carries user configuration
  upgrades across this change and starts up
- **THEN** the first-run marker is set WITHOUT inserting any GetComics indexer or
  DDL client row, so an operator who deliberately runs without a DDL provider is
  never injected with one

#### Scenario: Newznab and SABnzbd are never seeded

- **WHEN** first-run seeding runs
- **THEN** no Newznab indexer row and no SABnzbd download-client row is created —
  only the keyless GetComics/built-in-DDL pair is seeded, and credentialed
  providers remain opt-in

## MODIFIED Requirements

### Requirement: FRG-DEP-003 — configuration via environment variables and config file

The system SHALL read configuration from a versioned config file under `/config`
with environment-variable overrides taking precedence, and SHALL document every
setting with its default; secrets (API keys, credentials) SHALL be supplied via
environment variables or the config file, never baked into the image. The
documented configuration surface SHALL list ONLY settings that a component of the
system actually consumes: it SHALL NOT advertise a global credential field for a
credential no component reads globally. In particular, per-provider credentials
(indexer and download-client API keys) live in per-provider row settings — NOT as
global config-file fields — so the only global secret placeholder in the
documented config is the ComicVine API key. Removing a previously-documented global
setting from the model SHALL NOT break an existing config file that still carries
the stale key: the unknown key is ignored with a logged warning rather than
failing startup.

- **Milestone**: M1
- **Source**: mylar-feature-surface.md §7 (config surface, 34 sections — foragerr's
  is deliberately far smaller); CLAUDE.md Secrets section; m2-first-run-defaults
  (removal of the three never-consumed global credential fields
  `dognzb_api_key`/`nzbsu_api_key`/`sabnzbd_api_key`).
- **Notes**: Env-over-file precedence is the container-native divergence from
  Mylar's ini-only model. Validation of the values is baselined under NFR (config
  validation) — dedup hint. m2-first-run-defaults: the three vestigial DogNZB /
  NZB.su / SAB global `SecretStr` fields (verified zero consumers) are removed from
  the model; `extra="ignore"` plus the load-time unknown-key pop keep an old
  `config.yaml` loading, and the documented renderer stops emitting their
  placeholders. Provider credentials are entered per-row through the Settings UI.

#### Scenario: First run generates a documented config file

- **WHEN** the application starts against a fresh config directory containing no
  config file
- **THEN** it generates `config.yaml` in the config directory containing every
  setting with its default value and an explanatory comment, and the application
  runs with those defaults

#### Scenario: Config file value takes effect

- **WHEN** a setting (e.g., log level) is changed in `config.yaml` and the
  application is restarted with no corresponding environment variable set
- **THEN** the application runs with the file's value rather than the built-in
  default

#### Scenario: Environment variable overrides the config file

- **WHEN** the same setting is present in `config.yaml` and also set via its
  `FORAGERR_*` environment variable with a different value
- **THEN** the environment variable's value wins, observably (e.g., in effective
  log verbosity or the reported effective config)

#### Scenario: Secrets have no baked-in defaults

- **WHEN** the application starts with no secret values supplied via environment or
  config file
- **THEN** every secret-typed setting is empty/unset — no default key or credential
  value exists anywhere in the codebase or generated config — and the generated
  `config.yaml` contains only empty/commented placeholders for secrets

#### Scenario: Documented config advertises no credential no component consumes

- **WHEN** the documented `config.yaml` is generated
- **THEN** it contains NO global credential placeholder for a credential that no
  component reads globally — specifically no `dognzb_api_key`, `nzbsu_api_key`, or
  `sabnzbd_api_key` line — and the only global secret placeholder present is
  `comicvine_api_key`

#### Scenario: A stale removed credential key keeps an existing config loading

- **WHEN** an existing `config.yaml` still carries a removed global credential key
  (e.g. `dognzb_api_key`) and the application starts
- **THEN** startup succeeds, the unknown key is ignored with a logged warning, and
  no removed credential field is reintroduced as an effective setting
