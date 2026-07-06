Work areas A, B, C, and D are parallelizable by file ownership (separate
worktrees per FRG-PROC-008): A = `config.py` + the config-resource API; B = the DB
migration + startup seeding; C = the frontend; D = docs/security/traceability.
Every requirement gets at least one tagged test (FRG-PROC-004): pytest
`@pytest.mark.req("FRG-...")`, vitest ID-in-test-name.

## A. Backend — config surface + ComicVine credential settings API

- [x] A.1 Remove the three dead global credential fields (`dognzb_api_key`,
      `nzbsu_api_key`, `sabnzbd_api_key`) from `Settings` in
      `backend/src/foragerr/config.py`. Tagged tests: the generated documented
      `config.yaml` contains none of the three keys and still contains the
      `comicvine_api_key` placeholder; a `config.yaml` carrying all three stale
      keys loads cleanly with a logged unknown-key warning (no startup failure).
      [FRG-DEP-003]
- [x] A.2 New ComicVine credential settings resource (e.g. `GET/PUT
      /api/v1/config/general`): GET returns `{configured, source ∈
      unset|file|environment}` and NEVER the key value, reading
      `os.environ["FORAGERR_COMICVINE_API_KEY"]` to distinguish env from file. PUT
      persists a non-blank key via the `_apply` read-modify-write-reload shape
      (merge → validate `Settings` → `atomic_write_text(render_documented_config(
      merged))` → swap `app.state.settings` → `register_secret`), under the
      existing config write lock; a blank key keeps the stored value; when source
      is `environment` the PUT is rejected as env-managed. Tagged tests: GET hides
      the value + reports each source; PUT persists + applies live (no restart) +
      no key in body/log; blank keeps stored; env-set → read-only rejection.
      [FRG-API-018]
- [x] A.3 ComicVine connectivity-test action (e.g. `POST
      /api/v1/config/comicvine/test`) exercising the effective key and returning a
      success/failure result without leaking the key. Tagged test: success and
      failure results; no key in body/log. [FRG-API-018]
- [x] A.4 Live-apply verification for the metadata client: assert a UI-written key
      is used by the next ComicVine request without a restart (per-request client
      reads `app.state.settings`), and that an env-set key stays effective. Tagged
      tests per the FRG-META-002 delta scenarios (live-apply; env precedence
      preserved + reported). [FRG-META-002]

## B. Backend — first-run default DDL provider seeding

- [x] B.1 Forward-only Alembic migration adding the first-run seed marker (a
      singleton meta/app-state row), and pre-setting it as already-seeded for an
      established database (default heuristic: any pre-existing
      `indexers`/`download_clients`/`series` row) so an upgrade never injects
      providers. Tagged test: fresh DB leaves the marker unset; a DB with existing
      user config has the marker pre-set. [FRG-DEP-013]
- [x] B.2 Startup provisioning step (runs after `import foragerr.ddl` populates the
      registry and after migrations): if the marker is unset, seed one enabled
      GetComics indexer row (`implementation="getcomics"`, `protocol="ddl"`,
      `GetComicsSettings()` defaults) and one enabled built-in DDL client row
      (`implementation="ddl"`, `protocol="ddl"`, `BuiltinDdlSettings()` defaults)
      via the repo helpers, idempotent by the reserved name `"GetComics"`, then set
      the marker; wire it into the app startup sequence. Tagged tests: fresh start
      seeds exactly one enabled row in each table with default settings + sets the
      marker; deleting a seeded row and restarting does NOT recreate it (marker
      gate); Newznab/SAB are never seeded. [FRG-DEP-013]

## C. Frontend — Settings → General section + AddSeries link

- [x] C.1 New Settings → General screen (bespoke config-singleton / MediaManagement
      pattern): a masked write-only ComicVine key field (SchemaForm password
      widget — never echo stored value, `••••••••` when set, omit blank on save), a
      Test button on the `useTestProvider` pattern, and the env-managed read-only
      state driven by the resource's reported `source`. Add the nav item
      (`Sidebar.tsx`), route `/settings/general` (`App.tsx`), config query keys,
      and read/write/test hooks (namingHooks pattern). Vitest (ID in name): masked
      + write-only + blank-keeps-stored; save persists; Test reports success/
      failure without the key; env source → read-only. [FRG-UI-020]
- [x] C.2 Link the ComicVine credential-error guidance to the new section: wrap the
      "check Settings" prose in `AddSeries.tsx` and `LibraryImport.tsx` in a
      `<Link to="/settings/general">` (mirroring the existing no-root-folders link),
      keeping the `field="comicvine_api_key"` classifier. Vitest: the credential
      error renders a link to the General settings route. [FRG-UI-020]

## D. Docs, security, traceability, gate

- [x] D.1 Manual (FRG-PROC-011): `docs/manual/admin/secrets.md` +
      `docs/manual/admin/configuration.md` drop the three removed
      `dognzb_api_key`/`nzbsu_api_key`/`sabnzbd_api_key` rows and reword "four
      secret-typed settings"; `configuration.md` documents the UI ComicVine-key
      path (and that env still wins); `docs/manual/user/web-ui.md` documents the
      Settings → General section + Test button; `docs/manual/user/metadata.md` notes
      the UI key path; `docs/manual/user/downloads.md` (and/or `search.md`)
      documents the default-on GetComics/built-in-DDL first-run pair. Review
      `README.md` labelling. [FRG-PROC-011]
- [x] D.2 Security (FRG-PROC-006): `docs/security/` delta — (a) STRIDE note on the
      new ComicVine key-write endpoint (write-only over the API, log-redaction on
      write, no new residual beyond RISK-020 no-auth + RISK-013 plaintext-at-rest);
      (b) threat-model COMP-6 note + risk-register update recording that default-on
      DDL seeding shifts the accepted RISK-015 / RISK-016 posture from opt-in to
      default-enabled, with the review trigger. No new FRG-SEC requirement; no
      egress/allowlist change (getcomics already on `KNOWN_DDL_HOSTS`, default
      base_url public). [FRG-PROC-006]
- [x] D.3 Registry flips (FRG-API-018, FRG-UI-020, FRG-DEP-013 → implemented;
      FRG-DEP-003, FRG-META-002 stay implemented) + traceability matrix regen +
      `tools/soup_check.py` exit 0 (no SOUP change expected). [FRG-PROC-004,
      FRG-PROC-005, FRG-PROC-012]
- [x] D.4 Suites green (backend + frontend + e2e); pre-merge review cycle
      (`/code-review` + `/simplify`) + gate angles; fixes; archive; `--no-ff` merge
      with full suite green; main suites; tag. [FRG-PROC-007]
