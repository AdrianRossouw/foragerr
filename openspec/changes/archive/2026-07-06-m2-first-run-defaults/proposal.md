## Why

Testing the configuration surface (Adrian, 2026-07-06) surfaced three defects in
how foragerr presents and provisions its credential + provider model:

1. **The documented `config.yaml` advertises three dead global credential
   fields.** `dognzb_api_key`, `nzbsu_api_key`, and `sabnzbd_api_key` are
   `Settings` fields (env-suppliable `SecretStr`) rendered into the first-run
   `config.yaml` as commented-out secret placeholders — yet they have ZERO
   consumers anywhere in the codebase (verified: no reference outside
   `config.py`). Indexer rows and download-client rows each store their own
   `api_key` inside per-row settings JSON entered through the Settings UI schema
   forms. These fields are vestigial M1 leftovers that actively mislead an
   operator about the configuration model (they imply DogNZB/NZB.su/SAB keys are
   global config-file settings when they are per-provider row settings).

2. **The ComicVine API key — the one legitimately global credential — cannot be
   set anywhere but `config.yaml`/env.** When a ComicVine lookup fails on a
   missing/invalid key, AddSeries tells the user to "check Settings" — but NO
   Settings screen has a ComicVine field and NO settings-write API exists for it
   (verified). The guidance points at a door that does not exist.

3. **On first run there is no working acquisition pipeline at all.** The indexer
   and download-client tables start empty, so a fresh install can find nothing
   and download nothing until the operator manually configures a provider — even
   though a fully **keyless** pipeline already ships: the GetComics DDL search
   provider (an indexer implementation) plus the built-in DDL download client.
   Newznab/SAB need credentials; the DDL pair needs none. A first-run user should
   land on a usable default rather than an inert shell.

## What Changes

- **Remove the three dead global credential fields (MODIFIED FRG-DEP-003)**:
  delete `dognzb_api_key`, `nzbsu_api_key`, and `sabnzbd_api_key` from the
  `Settings` model. The documented-config surface shrinks (those commented secret
  placeholders disappear); the ONLY global secret placeholder left is
  `comicvine_api_key`. `extra="ignore"` plus `load_settings`' explicit
  unknown-key pop mean an existing `config.yaml` that still carries the stale
  keys keeps loading (they are ignored with a logged warning, never a startup
  failure) — verified in `config.py:142` (`extra="ignore"`) and
  `config.py:873-878`. Per-provider credentials continue to live in provider rows,
  as they already do.

- **ComicVine API key configurable in the UI (ADDED FRG-API-018, MODIFIED
  FRG-META-002, ADDED FRG-UI-020)**: a new **Settings → General** section with a
  masked, write-only ComicVine key field and a "Test" connectivity button
  (mirroring the indexer test-button pattern, FRG-IDX-003/FRG-UI-008), backed by a
  new config-resource endpoint that:
  - **reports source, never the value** — GET returns whether the key is
    configured and its SOURCE (unset / set-in-file / set-by-environment) but never
    the key itself;
  - **persists a UI-written key** into `config.yaml` through the existing atomic
    documented-config writer (`render_documented_config` already preserves a
    supplied secret value uncommented — `config.py:780-786` — so no new secrets
    file is needed) and **applies it live without a restart** by swapping
    `app.state.settings` (the ComicVine client is constructed per request and reads
    the key fresh — `metadata/comicvine.py:117`, `api/series.py:350-353` — so the
    swap is sufficient);
  - **honours env precedence** — because `FORAGERR_COMICVINE_API_KEY` outranks the
    file value (`config.py:592`), when the key is env-supplied the API reports
    `source="environment"` and the UI renders a read-only "set by environment"
    state instead of a silently-ineffective editor.
  The AddSeries (and library-import) "check Settings" credential-failure guidance
  gains a link into the new section.

- **First-run default DDL indexer + download client (ADDED FRG-DEP-013)**: on a
  genuinely first-run (fresh) install, seed exactly one **enabled** GetComics DDL
  indexer row (`implementation="getcomics"`, `protocol="ddl"`, default
  `GetComicsSettings`) and one **enabled** built-in DDL download-client row
  (`implementation="ddl"`, `protocol="ddl"`, default `BuiltinDdlSettings`), so a
  keyless search→grab→download pipeline works out of the box. Seeding is recorded
  by a persisted marker (NOT "tables empty") so a provider the user later deletes
  is never resurrected on restart, and an established install upgrading from a
  prior version is marked seeded WITHOUT injecting providers. Newznab/SAB remain
  opt-in.

## Capabilities

### New Capabilities

- `api`: FRG-API-018 (ComicVine credential settings resource — status/source read,
  write-through-config-writer, live-apply, connectivity test; never leaks the key).
- `ui`: FRG-UI-020 (Settings → General ComicVine key field + Test button +
  env-read-only state; AddSeries credential-error link).
- `dep`: FRG-DEP-013 (first-run seeding of the default keyless DDL provider pair,
  guarded by a persisted seed marker).

### Modified Capabilities

- `dep`: FRG-DEP-003 (documented config surface no longer advertises the dead
  DogNZB/NZB.su/SAB global credential fields; only genuinely-consumed globals
  remain).
- `meta`: FRG-META-002 (the ComicVine key may now be supplied via env, config
  file, OR the settings UI persisted to the config file, and a UI update applies
  without restart while env precedence is preserved and reported).

## Impact

- **Code**: backend — `config.py` drops three fields; a new config-resource
  endpoint (GET status/source, PUT key via `_apply`-style read-modify-write-reload
  reusing `render_documented_config` + `atomic_write_text`, POST connectivity test)
  that reads `os.environ["FORAGERR_COMICVINE_API_KEY"]` to report source; a
  first-run seeding step (a forward-only migration for the marker + a startup
  provisioning hook that runs after `import foragerr.ddl` so the registry is
  populated, seeding the two rows idempotently by reserved name). Frontend — a new
  `Settings → General` bespoke config-singleton screen (MediaManagement pattern)
  with a masked write-only key field (SchemaForm password widget) + Test button
  (useTestProvider pattern), a nav item + route `/settings/general`, config
  read/write/test hooks (namingHooks pattern), and a `<Link>` from the AddSeries /
  LibraryImport credential-error prose.
- **DB**: one new forward-only migration adding a first-run seed marker (and, on an
  established install, pre-setting it); the seeded rows use the EXISTING `indexers`
  and `download_clients` tables unchanged (no schema change to those tables).
- **Security docs** (FRG-PROC-006): TWO deltas. (1) The new **key-write path** is
  a new state-changing endpoint that accepts a secret from the (unauthenticated,
  tailnet-only — RISK-020) UI and persists it to `config.yaml`: a STRIDE note that
  the key is write-only over the API (GET never returns it), is registered with the
  log-redaction filter on write, and inherits the accepted no-auth posture; no new
  residual beyond RISK-020/RISK-013 (plaintext-at-rest, already accepted). (2)
  **Default-on DDL** shifts the accepted RISK-015 (single hardcoded getcomics
  upstream → malware-channel) and RISK-016 (ToS-sensitive scraping automation)
  posture from opt-in to default-enabled — a threat-model COMP-6 note + a risk
  register update recording the default-on decision and its review trigger. No new
  attack surface is added (the DDL code paths already exist and are threat-modeled);
  getcomics.org is already on `KNOWN_DDL_HOSTS` and the default `base_url` is
  public, so NO egress/allowlist change is required. **Declared: security-docs
  deltas ARE required and are tasks in this change; no new FRG-SEC requirement.**
- **Manual** (FRG-PROC-011): user-facing and admin-facing behaviour changes, so:
  `docs/manual/admin/secrets.md` and `docs/manual/admin/configuration.md` drop the
  three removed `dognzb_api_key`/`nzbsu_api_key`/`sabnzbd_api_key` rows and reword
  "four secret-typed settings" accordingly; `docs/manual/admin/configuration.md`
  documents that the ComicVine key can now also be set in the UI (and that env
  still wins); `docs/manual/user/web-ui.md` documents the new Settings → General
  section + Test button; `docs/manual/user/metadata.md` notes the UI key path; and
  the first-run default DDL provider pair is documented in
  `docs/manual/user/downloads.md` (and/or `search.md`) with the security note that
  it is default-on scraping. `README.md` labelling reviewed for the config surface
  change.
- **Dependencies / SOUP** (FRG-PROC-012): none — no new libraries (the frontend
  reuses SchemaForm, the provider test hook, and the config-form pattern; the
  backend reuses pydantic-settings, the config writer, and Alembic).
  `tools/soup_check.py` stays at exit 0.

## Non-goals

- No at-rest encryption of secrets (still FRG-AUTH-008, M5) — a UI-written key is
  stored in plaintext in `config.yaml` exactly as an env/file key is today
  (RISK-013).
- No general "settings resource for every field" — the new endpoint covers the
  ComicVine credential (and is a home for future genuinely-global settings), not a
  wholesale config API.
- No move of per-provider (DogNZB/NZB.su/SAB) credentials into global config — they
  stay per-row; this change only removes the never-consumed global fields.
- No seeding of Newznab or SABnzbd providers (they need credentials and stay
  opt-in), and no auto-add/auto-search behaviour beyond making the default DDL
  provider pair present and enabled.
- No change to the ComicVine lookup/suggest error contract (`field="comicvine_api_key"`,
  503) — only the guidance now links to a real Settings section.

## Approval

This change is authored under the standing **M2/M3 grant** Adrian issued on
2026-07-06 (recorded in memory `m2-m3-planning.md`): the orchestrator runs the
decomposed M2/M3 changes autonomously under FRG-PROC-009. His standing words,
verbatim from the grant:

> keep going with m2/m3 and all their related changes as you go. I'll come check in later

In addition, THIS specific change was raised and approved in-session on
2026-07-06: Adrian was testing the configuration surface, challenged the three
dead credential fields and the missing ComicVine key UI, and — after the
three-decision scope (remove dead fields; ComicVine key in the UI with a Test
button; first-run default DDL provider) was put to him — approved it directly:

> yip. let's do it

together with the follow-up that the ComicVine key belongs in a proper Settings
UI section (the ComicVine-UI follow-up). This change (m2-first-run-defaults, M2
change 5.5) falls squarely within the standing grant's scope and additionally has
this explicit owner go-ahead.
