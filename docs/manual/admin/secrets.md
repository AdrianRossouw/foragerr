# Secrets handling

foragerr currently holds four secret-typed settings, all empty by default and all
supplied only by you at deploy time:

- `comicvine_api_key` (`FORAGERR_COMICVINE_API_KEY`)
- `dognzb_api_key` (`FORAGERR_DOGNZB_API_KEY`)
- `nzbsu_api_key` (`FORAGERR_NZBSU_API_KEY`)
- `sabnzbd_api_key` (`FORAGERR_SABNZBD_API_KEY`)

## How to supply them

Set each as an environment variable (directly, or via a `.env` file consumed by your
process manager / Docker Compose), or uncomment and fill in the corresponding line in
`config.yaml`. Environment variables take precedence over the config file (see
`configuration.md`). Never hardcode a key in a Dockerfile, image layer, or committed
file — see FRG-DEP-005 in `openspec/specs/dep/spec.md`.

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
file) is a later milestone (`FRG-AUTH-008`, targeted M3) — it applies to secrets a
user enters through a UI once one exists (e.g. an indexer API key saved through
settings), not to the environment-sourced values above. Until then, treat the
`/config` volume itself as sensitive: anyone who can read the SQLite database or
`config.yaml` on disk can read any secret stored there in plaintext. Restrict
filesystem access to the config volume accordingly.
