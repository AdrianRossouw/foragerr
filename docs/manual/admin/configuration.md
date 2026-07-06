# Configuration

foragerr reads its configuration from three layers, in precedence order (highest
first):

1. `FORAGERR_*` environment variables
2. `<config_dir>/config.yaml`
3. built-in defaults

The config directory itself is set by the `FORAGERR_CONFIG_DIR` environment variable
(default `/config`) and holds **all** persistent state: the SQLite database, the
config file, logs, backups, and caches. On first run against an empty config
directory, foragerr generates a fully-documented `config.yaml` there — every setting
listed with its default value and an explanatory comment; secret fields are written
only as commented-out placeholders, never with a real value.

Configuration is validated as a whole at startup; an invalid value fails fast with a
field-precise error rather than starting in a partially-broken state. A handful of
interval settings (see table) are clamped into a documented safe range with a warning
instead of failing outright if you set them out of range.

## Settings reference

Source: `backend/src/foragerr/config.py`. Every setting below is read as
`FORAGERR_<NAME>` (uppercased) from the environment, or as the same name (lowercase)
under the top level of `config.yaml`.

| Setting | Env var | Default | Notes |
|---|---|---|---|
| `config_dir` | `FORAGERR_CONFIG_DIR` | `/config` | Environment-only; not read from `config.yaml` itself. |
| `host` | `FORAGERR_HOST` | `0.0.0.0` | Interface the HTTP listener binds to. |
| `port` | `FORAGERR_PORT` | `8789` | TCP port for the HTTP listener. |
| `log_level` | `FORAGERR_LOG_LEVEL` | `INFO` | One of DEBUG/INFO/WARNING/ERROR/CRITICAL. |
| `log_max_bytes` | `FORAGERR_LOG_MAX_BYTES` | `10000000` | Log file size before rotation. |
| `log_backup_count` | `FORAGERR_LOG_BACKUP_COUNT` | `5` | Rotated log files retained. |
| `scheduler_tick_seconds` | `FORAGERR_SCHEDULER_TICK_SECONDS` | `60` | Clamped to 5-60. |
| `http_connect_timeout_seconds` | `FORAGERR_HTTP_CONNECT_TIMEOUT_SECONDS` | `10.0` | Outbound HTTP connect timeout, all clients. |
| `http_read_timeout_seconds` | `FORAGERR_HTTP_READ_TIMEOUT_SECONDS` | `30.0` | Outbound HTTP read timeout. |
| `http_write_timeout_seconds` | `FORAGERR_HTTP_WRITE_TIMEOUT_SECONDS` | `30.0` | Outbound HTTP write timeout. |
| `http_pool_timeout_seconds` | `FORAGERR_HTTP_POOL_TIMEOUT_SECONDS` | `30.0` | Max wait for a pooled outbound connection. |
| `http_max_response_bytes` | `FORAGERR_HTTP_MAX_RESPONSE_BYTES` | `26214400` (25 MiB) | Byte cap on outbound response bodies; callers may lower, never raise. |
| `db_busy_timeout_ms` | `FORAGERR_DB_BUSY_TIMEOUT_MS` | `5000` | SQLite `busy_timeout`, all connections. |
| `db_backup_retention` | `FORAGERR_DB_BACKUP_RETENTION` | `3` | Pre-migration DB backups retained. |
| `db_backup_interval_seconds` | `FORAGERR_DB_BACKUP_INTERVAL_SECONDS` | `86400` (daily) | How often the scheduled `backup-database` task runs. Minimum 3600 (1 hour); a smaller value is rejected at load. See "Scheduled backups" below. |
| `db_scheduled_backup_retention` | `FORAGERR_DB_SCHEDULED_BACKUP_RETENTION` | `7` | Number of scheduled backups kept under `backups/scheduled-*`; independent of `db_backup_retention` (the pre-migration pool). |
| `workers_search` | `FORAGERR_WORKERS_SEARCH` | `1` | Worker count, "search" workload (keep at 1 for indexer politeness). |
| `workers_download` | `FORAGERR_WORKERS_DOWNLOAD` | `1` | Worker count, "download" workload (SAB tracking + DDL). |
| `workers_pp` | `FORAGERR_WORKERS_PP` | `1` | Worker count, post-processing workload. |
| `workers_default` | `FORAGERR_WORKERS_DEFAULT` | `2` | Worker count, everything unclassified. |
| `shutdown_grace_seconds` | `FORAGERR_SHUTDOWN_GRACE_SECONDS` | `25` | Clamped to 1-29 (must stay under 30s). |
| `job_history_retention_days` | `FORAGERR_JOB_HISTORY_RETENTION_DAYS` | `30` | Days of job history kept before pruning. |
| `usenet_retention_days` | `FORAGERR_USENET_RETENTION_DAYS` | `0` | Global usenet retention; 0 disables. Per-indexer override always wins. |
| `backlog_search_interval_seconds` | `FORAGERR_BACKLOG_SEARCH_INTERVAL_SECONDS` | `21600` (6h) | Minimum 1 hour. |
| `backlog_search_delay_seconds` | `FORAGERR_BACKLOG_SEARCH_DELAY_SECONDS` | `30` | Clamped **up** to a 30s floor if set lower. |
| `comicvine_api_key` | `FORAGERR_COMICVINE_API_KEY` | *(empty, secret)* | See `secrets.md`. Settable in the UI (Settings → General) as well as here — see "Setting the ComicVine key" below. |
| `comicvine_base_url` | `FORAGERR_COMICVINE_BASE_URL` | `https://comicvine.gamespot.com/api` | ComicVine API base. Leave at the default; overridden only to point the metadata client at a fixture server (the e2e harness). Every request carries your API key, so the scheme **must be https** — a plain-http value is refused at startup unless `comicvine_insecure_base` opts in. The egress policy additionally applies to the resolved host. |
| `comicvine_insecure_base` | `FORAGERR_COMICVINE_INSECURE_BASE` | `false` | Test affordance only: permits a plain-http `comicvine_base_url` on a fixture network. Never set in production. |
| `comicvine_min_interval_seconds` | `FORAGERR_COMICVINE_MIN_INTERVAL_SECONDS` | `2.0` | Minimum seconds between any two ComicVine requests, process-wide. |
| `comicvine_page_size` | `FORAGERR_COMICVINE_PAGE_SIZE` | `100` | ComicVine's own page-size cap. |
| `comicvine_max_pages` | `FORAGERR_COMICVINE_MAX_PAGES` | `200` | Hard cap on pages walked per list endpoint. |
| `comicvine_search_result_cap` | `FORAGERR_COMICVINE_SEARCH_RESULT_CAP` | `1000` | Series-search candidates cap; truncation is visible. |
| `comicvine_ignored_publishers` | `FORAGERR_COMICVINE_IGNORED_PUBLISHERS` | *(empty)* | Comma-separated, case-insensitive. |
| `comicvine_image_hosts` | `FORAGERR_COMICVINE_IMAGE_HOSTS` | `comicvine.gamespot.com,comicvine1.cbsistatic.com,static.comicvine.com` | Allowlisted cover-image hostnames. |
| `track_downloads_interval_seconds` | `FORAGERR_TRACK_DOWNLOADS_INTERVAL_SECONDS` | `60` | Minimum 60s (download pool is serialized). |
| `auto_redownload_failed` | `FORAGERR_AUTO_REDOWNLOAD_FAILED` | `true` | Self-healing re-search after a failed download. |
| `opds_base_path` | `FORAGERR_OPDS_BASE_PATH` | `/opds` | Base URL path the OPDS catalog is mounted at. Must start with `/`; trailing slash stripped; in-feed links are built relative to it. |
| `opds_page_size` | `FORAGERR_OPDS_PAGE_SIZE` | `50` | Default entries per OPDS feed page when the client doesn't ask. |
| `opds_page_size_cap` | `FORAGERR_OPDS_PAGE_SIZE_CAP` | `100` | Hard upper bound on OPDS page size; larger client requests are clamped. |
| `rename_enabled` | `FORAGERR_RENAME_ENABLED` | `true` | Rename files on import per the naming template. Off = keep source filenames. |
| `file_naming_template` | `FORAGERR_FILE_NAMING_TEMPLATE` | `{Series Title} {Issue Number:000} ({Year}) [__{IssueId}__]` | Token template for imported file names. Must render a name that re-parses to the same issue (validated at startup/save). |
| `folder_naming_template` | `FORAGERR_FOLDER_NAMING_TEMPLATE` | `{Series Title} ({Year})` | Token template for series folders. |
| `replace_illegal_characters` | `FORAGERR_REPLACE_ILLEGAL_CHARACTERS` | `true` | Replace filesystem-illegal characters in rendered names (off = strip). |
| `import_transfer_mode` | `FORAGERR_IMPORT_TRANSFER_MODE` | `move` | How download imports place files: `move`, `copy`, or `hardlink` (falls back to copy across volumes). |
| `library_import_mode` | `FORAGERR_LIBRARY_IMPORT_MODE` | `in_place` | How the existing-library import treats files already under a root: `in_place` (never moved) or `move`. |
| `duplicate_constraint` | `FORAGERR_DUPLICATE_CONSTRAINT` | `larger-size` | Same-format-rank duplicate arbitration: `larger-size` or `preferred-format`. Fixed-release markers (`(f1)`/`(f2)`) always win. Profile-rank upgrades/downgrades are unaffected. |
| `duplicate_dump_path` | `FORAGERR_DUPLICATE_DUMP_PATH` | *(empty)* | Directory losing duplicate files are moved to (dated subfolders). **Empty = the normal recycle/delete path applies.** Never pruned by recycle-bin retention. |
| `library_import_proposal_cap` | `FORAGERR_LIBRARY_IMPORT_PROPOSAL_CAP` | `50` | Max ComicVine match proposals one library-import scan performs (each is a rate-limited live search). Deferred groups keep their place and are proposed on later re-scans. |
| `library_import_similarity_floor` | `FORAGERR_LIBRARY_IMPORT_SIMILARITY_FLOOR` | `0.5` | Minimum name similarity (0–1) for a scan to attach a ComicVine proposal; below it the group stages as no-match for manual choice. |
| `recycle_bin_path` | `FORAGERR_RECYCLE_BIN_PATH` | *(empty)* | Directory upgrade-replaced and user-deleted files are moved to. **Empty = permanently delete.** Must be writable when set; destinations are confinement-checked. |
| `recycle_bin_retention_days` | `FORAGERR_RECYCLE_BIN_RETENTION_DAYS` | `0` | Days before housekeeping permanently prunes bin entries. `0` = keep forever. |
| `config_backup_retention` | `FORAGERR_CONFIG_BACKUP_RETENTION` | `3` | Pre-migration `config.yaml` backups kept under `backups/`. |
| `comicinfo_tag_on_import` | `FORAGERR_COMICINFO_TAG_ON_IMPORT` | `false` | Write ComicInfo.xml into imported cbz archives from the matched ComicVine record (atomic rewrite; a tagging failure never fails the import). |
| `listener_max_body_bytes` | `FORAGERR_LISTENER_MAX_BODY_BYTES` | `8388608` (8 MiB) | Max inbound HTTP request body size; floor 64 KiB. See "Listener resource limits" below. |
| `listener_max_header_bytes` | `FORAGERR_LISTENER_MAX_HEADER_BYTES` | `16384` (16 KiB) | Max total inbound HTTP header size; floor 1 KiB. |
| `listener_request_timeout_seconds` | `FORAGERR_LISTENER_REQUEST_TIMEOUT_SECONDS` | `30` | Max seconds a request may run before the listener aborts it. Clamped to 1-300. |
| `listener_rate_max_requests` | `FORAGERR_LISTENER_RATE_MAX_REQUESTS` | `240` | Per-client request cap per `listener_rate_window_seconds`. `0` disables the rate cap entirely. |
| `listener_rate_window_seconds` | `FORAGERR_LISTENER_RATE_WINDOW_SECONDS` | `1` | Sliding-window length (seconds) for the per-client rate cap. Clamped to 1-60. |
| `ws_max_connections` | `FORAGERR_WS_MAX_CONNECTIONS` | `32` | Max concurrent WebSocket connections; floor 1. |
| `ws_max_inbound_bytes` | `FORAGERR_WS_MAX_INBOUND_BYTES` | `4096` (4 KiB) | Max size of a single inbound WebSocket frame; floor 64 bytes. |
| `ws_max_inbound_messages_per_second` | `FORAGERR_WS_MAX_INBOUND_MESSAGES_PER_SECOND` | `10` | Max sustained inbound WebSocket frames per second per socket; floor 1. |

Unknown keys found in `config.yaml` are ignored with a logged warning rather than
failing startup, so a config file from a slightly different version doesn't brick
the instance — this is how an older `config.yaml` carrying the now-removed
`dognzb_api_key`/`nzbsu_api_key`/`sabnzbd_api_key` placeholders keeps loading
cleanly (see "Setting the ComicVine key" below for why those three were never
actually global settings).

## Setting the ComicVine key

`comicvine_api_key` is the only global credential foragerr has. It can be supplied
two ways, in the same precedence order as every other setting:

1. The `FORAGERR_COMICVINE_API_KEY` environment variable (wins if set).
2. Settings → General in the web UI — see `../user/web-ui.md` → "Settings" →
   "General". Saving there writes the key into `config.yaml` through the same
   documented-config writer as every other file-persisted setting; it applies
   immediately, no restart needed. If the environment variable is set, the
   General screen shows the field read-only with a note that it is
   environment-managed, rather than a save button that would have no effect.

The key is write-only everywhere it can be set: the General screen and the
`GET /api/v1/config/general` API report only whether a key is configured and its
source (unset / file / environment), never the value itself.

DogNZB, NZB.su, and SABnzbd credentials are **not** global settings — each is
entered per-provider in Settings → Indexers / Download Clients (a provider's own
JSON settings, stored with that provider's row), which is also where DDL provider
tuning lives. Earlier versions of this manual listed
`dognzb_api_key`/`nzbsu_api_key`/`sabnzbd_api_key` as global `config.yaml` settings;
they were never consumed by anything and have been removed from the `Settings`
model (`m2-first-run-defaults`) — a stale `config.yaml` that still carries them
keeps loading fine (see the unknown-key note above), the keys are just ignored.

## Listener resource limits

The `listener_*` and `ws_*` settings above are availability safety valves on the
inbound HTTP/WebSocket listener, not access control (foragerr has no
authentication in M1/M2 — see `network.md`). Their defaults are deliberately
generous so nothing in normal single-admin use is ever refused; they exist to
bound memory/CPU if something on the tailnet misbehaves or a client floods the
listener. If you ever see one of these responses, it means a limit was hit —
here's what each one means and where to look:

- **413 (Payload Too Large)** — a request body exceeded `listener_max_body_bytes`
  (default 8 MiB). foragerr's API only ever accepts small JSON bodies, so this
  should never happen in normal use; if it does, something sent an unusually
  large request.
- **431 (Request Header Fields Too Large)** — combined request headers exceeded
  `listener_max_header_bytes` (default 16 KiB).
- **503 (Service Unavailable)** — the request did not produce a response within
  `listener_request_timeout_seconds` (default 30s). This bounds only
  **time-to-first-response-byte**: once a handler starts streaming a response
  (an OPDS comic download, a large SPA asset) the timeout no longer applies, so
  a slow-but-working download is never truncated by this setting — only a
  handler that never responds at all is aborted.
- **429 (Too Many Requests)** — a single peer address exceeded
  `listener_rate_max_requests` requests within `listener_rate_window_seconds`
  (default 240 per 1s). The response carries a `Retry-After` header. Set
  `listener_rate_max_requests` to `0` to disable this cap entirely if it ever
  interferes with legitimate UI traffic (e.g. a busy React-Query fan-out on a
  slow link).
- **WebSocket close code 1013 (Try Again Later)** — the live-updates socket
  (`/api/v1/ws`) refused a new connection because `ws_max_connections`
  (default 32) concurrent sockets were already open. Existing connections are
  completely unaffected; refresh or retry once another tab/client disconnects.
- **A WebSocket connection closing unexpectedly** — if a client sends an
  inbound frame larger than `ws_max_inbound_bytes` (default 4 KiB) or more than
  `ws_max_inbound_messages_per_second` (default 10) frames per second, that
  socket is closed. The channel is server-push only (foragerr never expects
  meaningful inbound WebSocket traffic), so this should not occur from the
  normal web UI.

## Config-file precedence in practice

If you set the same value in both `config.yaml` and its `FORAGERR_*` environment
variable, the environment variable wins — this is deliberate so a Docker Compose
file (env vars) can override a persisted config file without editing it. To change a
setting persistently without an environment variable, edit `config.yaml` under the
config directory and restart.

## Config file versioning

`config.yaml` carries a `config_schema_version` stamp. On upgrade, an older file is
migrated forward one step at a time; before any rewrite the original is backed up to
`backups/pre-config-migration-<version>-<timestamp>/` (keeping the newest
`config_backup_retention` backups). A config stamped **newer** than the running
build refuses startup with a precise error and the file is left untouched — restore
the matching build or the backed-up file. Operator-set values survive migration
verbatim.

## Scheduled backups

Separately from the pre-migration/pre-config-migration safety copies above,
foragerr runs a **scheduled `backup-database` task** on `db_backup_interval_seconds`
(default daily). Each run:

1. runs a full `PRAGMA integrity_check` against the live database — a failing
   check **aborts the backup** (no new backup directory is written) and is
   surfaced as a database health error on the System → Health screen instead
   of silently rotating a copy of the corruption into the backup pool;
2. WAL-checkpoints and writes a consistent copy of the database (SQLite's
   online backup API — never a raw file copy of a live WAL database) plus a
   copy of `config.yaml`, both into a new
   `/config/backups/scheduled-<timestamp>/` directory;
3. prunes the `scheduled-*` pool to the newest `db_scheduled_backup_retention`
   directories (default 7), oldest first.

The `scheduled-*` pool is pruned independently of the `pre-migration-*` pool
(`db_backup_retention`) and the `pre-config-migration-*` pool
(`config_backup_retention`) — each prefix is retained on its own count, so
running low on one never evicts the other.

Because the scheduled backup is an ordinary scheduled task, it also shows up on
the System → Tasks screen with its interval and last/next run, and its
prominent **"Back up now"** button force-runs it on demand (the same
force-run mechanism every other task uses — see `../user/web-ui.md`).

**A backup is a plaintext-credential artifact.** Both the database and
`config.yaml` store the ComicVine, indexer (DogNZB, NZB.su), and SABnzbd API
keys in plaintext today — foragerr has no encryption-at-rest or secret store
yet — so every file under `/config/backups/` carries the same secrets as the
live configuration. This is a deliberately accepted risk
(`docs/security/risk-register.md` RISK-041), on the same footing as the
no-auth posture (RISK-020): backups never leave the container-private
`/config` volume (there is no cloud/remote/download-backup feature), they
inherit `/config`'s non-root PUID/PGID ownership, and secret values are never
logged. Treat `/config/backups/` with the same care as `/config` itself if you
ever copy it off the host.

See `deployment.md` → "Restoring from a backup" for how to use these files.
