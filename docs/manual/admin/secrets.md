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

## At-rest encryption of stored provider secrets

Provider secrets you enter through the UI — an indexer API key or a download-client
credential saved in Settings → Indexers / Download Clients — are **encrypted at rest**
in the SQLite database (`FRG-AUTH-008`). Each secret is stored as an
`enc:v1:<token>` value using authenticated encryption (Fernet: AES-128-CBC +
HMAC-SHA256); the encryption key is derived from a passphrase **you** supply, so the
database file alone — including any backup of it — does not expose your provider
secrets.

### `FORAGERR_SECRET_KEY` — the mandatory encryption passphrase

foragerr **requires** the `FORAGERR_SECRET_KEY` environment variable at startup and
refuses to start without it, naming the variable in the error. It is an
operator-chosen passphrase (any non-empty string) and is supplied through the
environment **only** — it is never read from, or written to, any file under `/config`
(unlike other settings, it has no `config.yaml` line). foragerr derives the actual
encryption key from it with scrypt and a random per-deployment salt; only the
non-secret salt and a sentinel check-value are persisted (in the database's
`keystore_meta` table). The passphrase itself never touches disk.

Choose a strong, random value and keep it stable across restarts. A good way to
generate one:

```bash
FORAGERR_SECRET_KEY="$(openssl rand -base64 32)"
```

Set it the same way as any other environment variable — directly, via your process
manager, or in the `environment:` block of your Docker Compose service (see
`deployment.md`). Never hardcode it in a Dockerfile or committed file.

### If the passphrase is lost or changed (recovery)

Losing or changing `FORAGERR_SECRET_KEY` costs **re-entry of your stored provider
secrets, never data**. Every stored provider secret is something you can re-obtain
and re-enter. If foragerr boots with a passphrase that does not match the one that
encrypted the stored secrets (for example, you restored the database into a
deployment with a different passphrase):

- foragerr **still starts normally**, and library browsing and OPDS are unaffected.
- Each affected integration reports **"credential unavailable — encryption key
  missing or changed; re-enter the secret"** on the health screen and behaves as
  unconfigured (it does not retry against the provider).
- **To recover:** either restore the original `FORAGERR_SECRET_KEY` value, or open
  Settings → Indexers / Download Clients and re-enter the affected secret. A saved
  secret is always re-encrypted under the current passphrase, which clears the
  warning for that integration.

### Backups

A backup taken after this release requires the **same** `FORAGERR_SECRET_KEY` to
yield usable provider credentials on restore. Restoring a backup without the matching
passphrase degrades to the re-entry path above (never data loss). The `/config`
volume no longer exposes provider secrets on its own, but still holds your library
database — continue to restrict filesystem access to it.
