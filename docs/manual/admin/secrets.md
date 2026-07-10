# Secrets handling

foragerr currently holds **one** global secret-typed setting, empty by default and
supplied only by you at deploy time:

- `comicvine_api_key` (`FORAGERR_COMICVINE_API_KEY`)

DogNZB, NZB.su, and SABnzbd credentials are **not** global settings — each is a
per-provider secret entered through Settings → Indexers / Download Clients in the
web UI and stored with that provider's row (see `../user/web-ui.md` → "Settings").
An earlier version of foragerr also carried `dognzb_api_key`, `nzbsu_api_key`, and
`sabnzbd_api_key` as global `config.yaml`/environment settings; they had no
consumers anywhere in the codebase and were removed (`m2-first-run-defaults`). A
`config.yaml` still carrying those three keys keeps loading — unknown keys are
ignored with a logged warning, never a startup failure (see `configuration.md`).

## How to supply the ComicVine key

Two ways, in the same precedence order as every other setting:

1. Set it as an environment variable (directly, or via a `.env` file consumed by
   your process manager / Docker Compose) — this always wins if set.
2. Uncomment and fill in the corresponding line in `config.yaml`, **or** set it from
   Settings → General in the web UI, which writes the same `config.yaml` line for
   you and applies the change immediately (no restart). See `configuration.md` →
   "Setting the ComicVine key" for the full precedence/read-only-when-env-set
   behaviour.

Never hardcode a key in a Dockerfile, image layer, or committed file — see
FRG-DEP-005 in `openspec/specs/dep/spec.md`.

`.env` files are gitignored in this repository and must never be committed. If you are
extending foragerr with a new integration that needs a credential, follow the same
pattern: an empty-by-default `SecretStr` setting, sourced from environment or
config file only.

## What foragerr does with them internally

Every secret setting is held as a `SecretStr` and, at the moment configuration is
loaded, its value self-registers with foragerr's log-redaction filter
(`foragerr.logging.register_secret`). In practice this means:

- No configuration dump, diagnostic output, or persisted file will ever contain a
  secret in plaintext.
- A full debug-level run of an add-series flow (search, volume fetch, issue
  pagination, cover fetch) never emits the ComicVine key anywhere in the logs, even
  though the key rides as a query parameter on every ComicVine request (ComicVine
  requires this — the guarantee is that *foragerr's own logging* redacts it).
- If a request carrying an API-key-shaped parameter raises and its traceback is
  logged, the key parameter is masked with a redaction placeholder rather than
  appearing in the traceback.

## What is not yet covered

At-rest encryption of secrets stored in the database (as opposed to environment/config
file) is not yet implemented (`FRG-AUTH-008`); it is tracked in
[the roadmap](../../roadmap.md). This gap is **live today**:
provider secrets entered through the UI — an indexer API key or download-client
credential saved in Settings → Indexers / Download Clients — are stored unencrypted
in the SQLite database. It does not affect the environment-sourced values above.
Until then, treat the
`/config` volume itself as sensitive: anyone who can read the SQLite database or
`config.yaml` on disk can read any secret stored there in plaintext. Restrict
filesystem access to the config volume accordingly.
