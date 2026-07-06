# Design — m2-first-run-defaults

## Context

Grounding (research-verified against the current tree at v0.2.6):

- **Config model** (`backend/src/foragerr/config.py`): `Settings(BaseSettings)`,
  `model_config = SettingsConfigDict(env_prefix="FORAGERR_", extra="ignore")`
  (`config.py:142`). `settings_customise_sources` returns
  `(env_settings, init_settings, dotenv_settings, file_secret_settings)`
  (`config.py:584-592`) — **env vars outrank init kwargs**, and `init_settings`
  is where `config.yaml` values enter (`load_settings` builds
  `Settings(config_dir=config_dir, **file_values)`, `config.py:881`).
- The three dead fields are `dognzb_api_key` (`config.py:396`), `nzbsu_api_key`
  (`:400`), `sabnzbd_api_key` (`:404`). Verified ZERO code consumers outside
  `config.py`; only doc references (`docs/manual/admin/secrets.md`,
  `configuration.md`). `load_settings` pops unknown file keys with a warning
  (`config.py:873-878`), so removing the fields keeps stale config files loading.
- **Documented-config renderer** `render_documented_config(values)`
  (`config.py:748-801`): the ONE renderer for first-run write and every rewrite.
  For a `SecretStr` field it emits a commented `#name: ""` placeholder UNLESS a
  non-empty value is supplied in `values`, in which case it writes the value
  **uncommented** (`config.py:780-786`). Unknown keys are preserved verbatim at
  the end (`:792-800`). `atomic_write_text` is the durable writer.
- **Config resource API** (`api/config_resources.py`, FRG-API-013): only
  `naming` + `mediamanagement` GET/PUT resources exist; both models declare "no
  secret fields", so there is NO endpoint that reads/writes `comicvine_api_key`.
  The shared `_apply` helper (`config_resources.py:150-190`) is the pattern:
  read raw `config.yaml` → merge PUT body → construct+validate `Settings` →
  `atomic_write_text(config_file, render_documented_config(merged))` →
  `request.app.state.settings = new_settings` → re-`register_secret(...)`, all
  under an `asyncio.Lock` (`_config_write_lock`).
- **ComicVine client seam**: `ComicVineClient.__init__` snapshots the key
  (`self._api_key = settings.comicvine_api_key.get_secret_value()`,
  `metadata/comicvine.py:117`) but the client is **per-request, never a
  singleton** — every call site constructs a fresh client from
  `request.app.state.settings` (`api/series.py:350-353`, `:404-407`;
  `library/flows/*`). No module-level cache of the key; it is read only through
  `Settings`, never `os.environ` directly. So **mutating `app.state.settings`
  is sufficient for live-apply** — the next request builds a client with the new
  key.
- **Credential-error prose**: backend static `COMICVINE_CREDENTIAL_MESSAGE`
  (`metadata/errors.py:25-27`) + 503 with `field="comicvine_api_key"`
  (`api/series.py:266-294`). Frontend classifier `isComicVineAuthError`
  (`frontend/src/api/fetcher.tsx:59-66`, matches the field not prose); prose in
  `AddSeries.tsx:60-62` and `LibraryImport.tsx:51-56`; both already use `<Link>`
  elsewhere (e.g. `AddSeries.tsx:248-251` → `/settings/media-management`).
- **Settings UI**: nav (`Sidebar.tsx` `NAV_GROUPS`) + routes (`App.tsx`) have
  exactly Media Management / Indexers / Download Clients — no General/Metadata.
  Config singletons use the **bespoke MediaManagement pattern** (a save-bar form
  backed by `GET/PUT /config/...`, hooks in `namingHooks.ts`), NOT the
  provider list+modal machinery. Masked write-only secrets are the SchemaForm
  password widget (`SchemaForm.tsx:146-160`): never echo the stored value, show
  `••••••••` when set, omit a blank field on save. The indexer Test button is
  `useTestProvider` POST `${apiBase}/test` (`providerHooks.ts:92-103`).
- **DDL provider pair**: GetComics indexer = `implementation="getcomics"`,
  `protocol="ddl"`, `GetComicsSettings` (defaults: `base_url="https://getcomics.org"`,
  `min_interval_seconds=15`, `max_pages=3`; all defaulted so `{}` is valid).
  Built-in DDL client = `implementation="ddl"`, `protocol="ddl"`,
  `BuiltinDdlSettings` (defaults: `host_priority="main,mirror,pixeldrain,mediafire,mega"`,
  `prefer_upscaled=True`; empty `{}` valid). Rows persist via
  `indexers/repo.py::create_indexer` and `downloads/repo.py::create_download_client`.
- **First-run seed precedent** (FRG-QUAL-002): `seed_default_format_profile`
  runs inside a forward-only Alembic migration with `INSERT ... WHERE NOT
  EXISTS` keyed on a reserved name; it fires once per database because migrations
  never re-run, so a user-deleted default is never recreated. Caveat: the DDL
  registry (`register_implementation("getcomics")`, `set_client_factory("ddl")`)
  is populated at `import foragerr.ddl` time, NOT in migrations.
- **Egress** (FRG-SEC-001 / FRG-DDL-012): the always-on egress policy is a
  private-address DENYlist (public getcomics.org passes); the per-provider
  allowlist `build_allowlist(base_url)` seeds from a hard-coded
  `KNOWN_DDL_HOSTS = {getcomics.org, getcomics.info, comicfiles.ru,
  readcomicsonline.ru}` plus the configured base host. getcomics.org is already
  allowed — **no egress change is needed to seed the default provider.**

## Goals / Non-Goals

**Goals:** shrink the config surface to only-consumed fields; make the one global
credential (ComicVine) UI-settable with correct env-precedence UX, live-apply,
and a Test button; ship a working keyless pipeline on first run without
resurrecting user-deleted providers.

**Non-Goals:** at-rest secret encryption; a wholesale settings API; moving
per-provider credentials to global config; seeding credentialed (Newznab/SAB)
providers; auto-add/auto-search.

## Decisions

1. **Scope A owns the documented-config surface via FRG-DEP-003, not a new id.**
   The documented `config.yaml` is FRG-DEP-003's concern ("document every
   setting"; the renderer docstring cites it). Removing the three dead fields is a
   MODIFIED FRG-DEP-003 — no new id. Removal is safe by construction:
   `extra="ignore"` + the explicit unknown-key pop mean an old file with the stale
   keys loads with a warning; the renderer stops emitting their placeholders; a
   config rewrite (migration or a future PUT) that carries a stale key forward
   lands it in the "keys not recognized by this build (preserved verbatim)" tail
   rather than as a live setting. Per-provider DogNZB/NZB.su/SAB keys are
   unaffected — they were always per-row.

2. **ComicVine credential resource: status/source out, key in, never round-trip
   (FRG-API-018, new).** A new config-resource endpoint (concrete shape for
   implementation: `GET /api/v1/config/general`, `PUT /api/v1/config/general`,
   `POST /api/v1/config/comicvine/test`). GET returns a credential STATUS object
   `{comicvine_api_key: {configured: bool, source: "unset"|"file"|"environment"}}`
   and NEVER the value. Source detection is the deliberate seam: the resource
   reads `os.environ.get("FORAGERR_COMICVINE_API_KEY")` directly — the ONE place
   in the app that needs to distinguish env from file, because pydantic-settings
   collapses both into `settings.comicvine_api_key` and the effective object
   cannot say which source won. If the env var is set → `source="environment"`;
   else if `settings.comicvine_api_key` is non-empty → `"file"`; else `"unset"`.

3. **Secret persistence: reuse the documented-config writer, no new secrets
   file.** A PUT with a non-blank key reuses the `_apply` read-modify-write-reload
   shape: merge `{comicvine_api_key: <plaintext>}` into the raw file dict, build +
   validate `Settings`, then `atomic_write_text(config_file,
   render_documented_config(merged))`. `render_documented_config` already writes a
   supplied secret uncommented (`config.py:783-784`), so the key lands in
   `config.yaml` as a real value — no separate secrets store is invented. A
   **blank** PUT means "keep the stored value" (mirrors the provider-form
   write-only convention) and does not clear it. After the write, mutate
   `app.state.settings` and re-`register_secret` the new value (as `_apply`
   already does). The GET status recomputes from the reloaded settings + env.

4. **Env precedence is surfaced, not silently defeated.** Because env outranks the
   file (`config.py:592`), a UI write while `FORAGERR_COMICVINE_API_KEY` is set
   would be shadowed on reload. Rather than let the operator type into a dead
   field, the resource reports `source="environment"` and the PUT is rejected as
   env-managed (a typed 409/validation error naming the env var) — and the UI
   renders the field read-only with "set by the FORAGERR_COMICVINE_API_KEY
   environment variable" guidance. This is the load-bearing UX decision the task
   calls out: no silently-ineffective editor.

5. **Live-apply by `app.state.settings` swap — no META mechanism change needed.**
   The client is per-request and reads the key fresh, so the existing swap seam
   (proven by `_apply`) applies the new key on the next request with no restart
   and no client-recreation plumbing. FRG-META-002 is MODIFIED only to (a) widen
   the key's sources to include the settings UI persisted to the config file and
   (b) state the no-restart guarantee and preserved env precedence — the redaction
   guarantees are unchanged.

6. **UI placement: a new Settings → General bespoke config screen (FRG-UI-020,
   new).** General (not Metadata): it is the Sonarr-shaped home for app-wide
   config singletons and the natural place for future global settings, and it
   avoids implying a metadata-provider abstraction foragerr does not have.
   (Metadata considered; rejected as narrower and less extensible.) The screen
   follows the MediaManagement save-bar pattern with the SchemaForm password
   widget for the key (write-only, `••••••••` when set), a Test button on the
   `useTestProvider` pattern hitting the connectivity endpoint, and the
   env-read-only state driven by the API's reported `source`. The AddSeries and
   LibraryImport credential-error prose gain a `<Link to="/settings/general">`
   exactly like the existing no-root-folders link. The "check Settings" behaviour
   is spec'd on FRG-UI-020 (the destination) rather than re-modifying the large
   FRG-UI-005 requirement, to avoid churn.

7. **First-run seed: persisted marker + startup provisioning hook, gated to fresh
   installs (FRG-DEP-013, new).** Mechanism:
   - A forward-only migration introduces a **first-run seed marker** (a singleton
     row in a small meta/app-state table). On an **established** database — one
     that already carries user configuration at migration time (default heuristic:
     any pre-existing `indexers`, `download_clients`, or `series` row) — the
     migration **pre-sets the marker as already-seeded WITHOUT inserting
     providers**, so an upgrading operator who deliberately runs without DDL is
     never injected. A genuinely fresh database gets no marker from the migration.
   - At startup, AFTER `import foragerr.ddl` has populated the registry (so the
     `getcomics`/`ddl` implementations exist) and after migrations, a provisioning
     step checks the marker. If unset: seed one enabled GetComics indexer row and
     one enabled built-in DDL client row via the repo helpers (idempotent
     `WHERE NOT EXISTS` on the reserved name `"GetComics"` as belt-and-suspenders),
     then set the marker. If set: do nothing.
   - Net predicate: seeding runs **at most once per database, on a first-run/empty
     install**, and the marker — not "tables empty" — is the gate, so deleting the
     seeded provider never brings it back on the next restart.
   - Seed values (from the model defaults): indexer `{name:"GetComics",
     implementation:"getcomics", protocol:"ddl", enabled:True, settings:
     GetComicsSettings() }`; client `{name:"GetComics", implementation:"ddl",
     protocol:"ddl", enabled:True, settings: BuiltinDdlSettings() }`.
   - Why a single DEP requirement rather than FRG-IDX-xxx + FRG-DL-xxx: the
     behaviour is one cross-cutting first-run provisioning property (a working
     keyless pipeline), not two independent model changes; the seeded rows use the
     existing FRG-IDX-001 / FRG-DL-002 models unchanged. (Split considered;
     rejected as ID sprawl for one behaviour, mirroring how FRG-QUAL-002 is a
     single requirement for its first-run seed.)

8. **Security is documentation-only under FRG-PROC-006 — no new FRG-SEC id.**
   Two deltas: (a) the key-write path — a new state-changing endpoint accepting a
   secret from the tailnet-only UI; the mitigations (write-only over the API,
   log-redaction on write, no new residual beyond the already-accepted RISK-020
   no-auth and RISK-013 plaintext-at-rest) are recorded as a STRIDE note. (b)
   default-on DDL — seeding shifts RISK-015 (single getcomics upstream →
   malware-channel) and RISK-016 (ToS-sensitive scraping) from opt-in to
   default-enabled; a threat-model COMP-6 note + a risk-register update records the
   default-on decision and its review trigger (any exposure beyond the tailnet,
   getcomics ToS change, or malware incident). No code attack surface is added and
   no egress/allowlist change is needed.

## Risks / Trade-offs

- **[Removing config fields breaks a hand-written config.yaml]** → it does not:
  `extra="ignore"` + the unknown-key pop keep old files loading (logged warning).
  Pinned by a tagged test loading a config carrying all three stale keys and
  asserting a clean startup + warning.
- **[A UI key write is silently shadowed by an env var]** → prevented by decision
  #4: the API reports `source="environment"` and rejects the PUT as env-managed;
  the UI is read-only. Pinned by a test with the env var set.
- **[Default-on DDL scraping surprises a privacy/ToS-sensitive operator]** → it is
  documented (manual + security note) and remains deletable (the marker ensures a
  deletion sticks). This is the accepted RISK-015/016 posture made default;
  review trigger recorded.
- **[Seeding injects providers into an established upgrade]** → prevented by the
  migration pre-setting the marker for databases that already carry user config;
  only genuinely fresh installs are seeded. The "established" heuristic is an
  implementation call with a stated default (any pre-existing indexer / download
  client / series row).
- **[The key persists in plaintext in config.yaml]** → identical to today's
  env/file key (RISK-013); at-rest encryption stays M5 (FRG-AUTH-008). Not a
  regression.

## Migration Plan

One new forward-only Alembic migration adds the first-run seed marker and
pre-sets it for established databases; it does not alter the `indexers` /
`download_clients` tables. No downgrade (forward-only per the project). Removing
the three config fields needs no migration (unknown keys are tolerated).
Rollback = revert the merge: the seeded rows are ordinary provider rows the
operator can delete, and the removed fields simply reappear.

## Open Questions

None blocking. Implementation-time calls, each with a stated default:
1. Exact "established install" heuristic for the marker pre-set — default: any
   pre-existing `indexers`/`download_clients`/`series` row ⇒ established (skip
   injection).
2. Concrete endpoint paths/section label — default: `Settings → General`,
   `GET/PUT /api/v1/config/general`, `POST /api/v1/config/comicvine/test`
   (Metadata was the alternative).
3. Whether the marker lives in a new tiny meta table or an existing singleton —
   default: a dedicated first-run marker row, mirroring how QUAL-002 keeps its
   seed self-contained.
